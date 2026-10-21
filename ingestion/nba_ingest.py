"""Ingest NBA data from the unofficial stats.nba.com API via nba_api.

Pulls, for a given season:
  - Player-level box score game logs   (one API call)
  - Team-level box score game logs     (one API call)
  - Advanced player and team stats     (one API call each, 1996-97 onward)
  - Play-by-play events                (one API call PER GAME - rate limited)
  - Player index and team dimension    (one API call + static data)

Raw results are written as parquet files to data/raw/. Load them into
DuckDB with scripts/load_to_duckdb.py.

stats.nba.com is unofficial and throttles aggressive clients, so every
request goes through a rate limiter (min interval between calls) plus
retry with exponential backoff. Do not remove the sleeps. Only transient
failures are retried - see call_endpoint.

Game logs are written one parquet per season (data/raw/player_game_logs/
{season}.parquet), so multi-season backfills are resumable: seasons whose
files already exist (and read as valid parquet) are skipped unless --force
is passed. Every write is atomic, so a killed run never leaves half a file.

Replacing a season file with one that has fewer rows is refused (the old
file stays, the run exits 1): a partial answer from the API should not
quietly erase good data. --allow-shrink overrides it.

Usage:
    python ingestion/nba_ingest.py                      # current season, 20 most recent games of PBP
    python ingestion/nba_ingest.py --season 2025-26 --pbp-games 50
    python ingestion/nba_ingest.py --backfill 1979-80   # everything from 1979-80 to now
    python ingestion/nba_ingest.py --all-pbp            # every game (slow: ~1300 calls)
    python ingestion/nba_ingest.py --smoke-test         # tiny pull to verify the API works
    python ingestion/nba_ingest.py --force --allow-shrink  # accept a smaller re-fetch
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from nba_api.stats.endpoints import (
    commonallplayers,
    leaguedashplayerstats,
    leaguedashteamstats,
    leaguegamelog,
    playbyplayv3,
    scheduleleaguev2,
)
from nba_api.stats.static import teams as static_teams

# Run as `python ingestion/nba_ingest.py`, so the repo root is not on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import paths
from core.io import (
    TransientError,
    atomic_write_parquet,
    backoff_delay,
    is_transient_status,
    is_valid_parquet,
    parquet_row_count,
    retry_transient,
)

RAW_DIR = paths.raw_dir()

# The NBA only publishes advanced box score stats (ratings, usage, PIE) from
# 1996-97 on; earlier seasons return zero rows. Everything before that is
# covered by the metrics dbt derives from raw box scores instead.
ADVANCED_FIRST_SEASON = "1996-97"

# --- Rate limiting -----------------------------------------------------------
# stats.nba.com has no published limits; community experience is that bursts
# get you temporarily blocked. Keep >= 1.5s between requests.
MIN_SECONDS_BETWEEN_REQUESTS = 1.5
REQUEST_TIMEOUT = 60
MAX_RETRIES = 4  # attempts in all: waits of 4s, 8s, 16s (plus jitter) between them
BACKOFF_BASE_SECONDS = 4

# What call_endpoint retries. A timeout is also how stats.nba.com turns away
# a client it dislikes - it stops answering rather than refusing - and that
# usually lifts after a while, so it is worth the wait.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    TransientError,
)

# Season files a re-fetch may not replace with fewer rows. Play-by-play is
# left out: its size follows --pbp-games, so shrinking is the normal case.
SHRINK_GUARDED = frozenset(
    {"player_game_logs", "team_game_logs", "player_advanced", "team_advanced", "schedule"}
)

log = logging.getLogger("nba_ingest")
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_at = time.monotonic()


def _request_once(endpoint_cls, kwargs: dict) -> pd.DataFrame:
    """One throttled request, with server errors raised as TransientError.

    nba_api never looks at the HTTP status: whatever comes back is parsed as
    JSON, so a 503 page surfaces as a JSONDecodeError (a ValueError) and a
    JSON error body without the expected result set as a KeyError. It does
    keep the status on the response object, so the endpoint is built without
    requesting and the request is made here, where a parse failure can
    still be traced to its status. Only a 429 or 5xx becomes transient. A
    200 that isn't JSON (a moved endpoint, a bad parameter answered with an
    error page) is not: asking again gets the same page.
    """
    _throttle()
    endpoint = endpoint_cls(timeout=REQUEST_TIMEOUT, get_request=False, **kwargs)
    try:
        endpoint.get_request()
    except (ValueError, KeyError) as exc:
        # nba_api has no public accessor for the status.
        status = getattr(getattr(endpoint, "nba_response", None), "_status_code", None)
        if isinstance(status, int) and is_transient_status(status):
            raise TransientError(
                f"HTTP {status} from {endpoint_cls.__name__}", status=status
            ) from exc
        raise
    return endpoint.get_data_frames()[0]


def call_endpoint(endpoint_cls, **kwargs) -> pd.DataFrame:
    """Call an nba_api endpoint with throttling, retrying transient failures.

    Returns the endpoint's first result set as a DataFrame. Timeouts,
    dropped connections, 429s and 5xx answers are retried with exponential
    backoff (nba_api doesn't expose response headers, so a 429's Retry-After
    can't be read here). Anything else raises at once: an empty result is a
    valid answer, and a TypeError, KeyError or unparseable 200 would fail
    the same way every time.
    """
    return retry_transient(
        lambda: _request_once(endpoint_cls, kwargs),
        attempts=MAX_RETRIES,
        transient=TRANSIENT_ERRORS,
        delay=lambda exc, attempt: backoff_delay(BACKOFF_BASE_SECONDS, attempt),
        label=endpoint_cls.__name__,
        log=log,
    )


# --- Season helpers ----------------------------------------------------------


def current_season(today: date | None = None) -> str:
    """NBA season string like '2025-26'. Seasons start in October; before
    October we are still in (or just finished) the season that began the
    prior year."""
    today = today or date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def season_range(start: str, end: str) -> list[str]:
    """All season strings from start to end inclusive, e.g. 1979-80..2025-26."""
    start_year, end_year = int(start[:4]), int(end[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start_year, end_year + 1)]


# --- Extractors ---------------------------------------------------------------


def fetch_player_game_logs(season: str) -> pd.DataFrame:
    log.info("Fetching player game logs for %s ...", season)
    df = call_endpoint(
        leaguegamelog.LeagueGameLog,
        season=season,
        player_or_team_abbreviation="P",
        season_type_all_star="Regular Season",
    )
    df["season"] = season
    log.info("  %d player-game rows", len(df))
    return df


def fetch_team_game_logs(season: str) -> pd.DataFrame:
    log.info("Fetching team game logs for %s ...", season)
    df = call_endpoint(
        leaguegamelog.LeagueGameLog,
        season=season,
        player_or_team_abbreviation="T",
        season_type_all_star="Regular Season",
    )
    df["season"] = season
    log.info("  %d team-game rows", len(df))
    return df


def fetch_play_by_play(game_ids: list[str], season: str) -> pd.DataFrame:
    log.info(
        "Fetching play-by-play for %d games (rate limited, ~%.0fs minimum) ...",
        len(game_ids),
        len(game_ids) * MIN_SECONDS_BETWEEN_REQUESTS,
    )
    frames = []
    for i, game_id in enumerate(game_ids, 1):
        # One bad game shouldn't sink the other nineteen. Programming errors
        # (a TypeError and the like) still propagate.
        try:
            df = call_endpoint(playbyplayv3.PlayByPlayV3, game_id=game_id)
        except (requests.RequestException, TransientError, ValueError, KeyError) as exc:
            log.error("  giving up on game %s: %s", game_id, exc)
            continue
        df["season"] = season
        frames.append(df)
        if i % 10 == 0 or i == len(game_ids):
            log.info("  %d/%d games done", i, len(game_ids))
    if not frames:
        raise RuntimeError("No play-by-play data could be fetched")
    return pd.concat(frames, ignore_index=True)


def has_advanced_stats(season: str) -> bool:
    return int(season[:4]) >= int(ADVANCED_FIRST_SEASON[:4])


def fetch_player_advanced(season: str) -> pd.DataFrame:
    """Official advanced player stats: OFF/DEF/NET rating, USG%, TS%, AST%,
    REB%, PACE, PIE. One call per season."""
    log.info("Fetching advanced player stats for %s ...", season)
    df = call_endpoint(
        leaguedashplayerstats.LeagueDashPlayerStats,
        season=season,
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
        season_type_all_star="Regular Season",
    )
    df["season"] = season
    log.info("  %d advanced player rows", len(df))
    return df


def fetch_team_advanced(season: str) -> pd.DataFrame:
    """Official advanced team stats: ratings, pace, four-factor components."""
    log.info("Fetching advanced team stats for %s ...", season)
    df = call_endpoint(
        leaguedashteamstats.LeagueDashTeamStats,
        season=season,
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
        season_type_all_star="Regular Season",
    )
    df["season"] = season
    log.info("  %d advanced team rows", len(df))
    return df


def fetch_schedule(season: str) -> pd.DataFrame:
    """The full published schedule including unplayed games.

    LeagueGameLog only returns games that have finished, so predicting a
    future slate needs this instead. The NBA publishes the next season's
    schedule in August, so this returns rows before the season starts.
    """
    df = call_endpoint(
        scheduleleaguev2.ScheduleLeagueV2,
        season=season,
        league_id="00",
    )
    log.info("Fetched %d scheduled games for %s", len(df), season)
    return df


def fetch_players(season: str) -> pd.DataFrame:
    log.info("Fetching player index ...")
    df = call_endpoint(
        commonallplayers.CommonAllPlayers,
        is_only_current_season=0,
        season=season,
    )
    log.info("  %d players", len(df))
    return df


def fetch_teams() -> pd.DataFrame:
    # Static data bundled with nba_api - no API call.
    df = pd.DataFrame(static_teams.get_teams())
    log.info("Loaded %d teams from nba_api static data", len(df))
    return df


# --- Main ---------------------------------------------------------------------


class ShrinkRefusedError(Exception):
    """A re-fetch came back with fewer rows than the file it would replace."""


def write_parquet(
    df: pd.DataFrame, name: str, season: str | None = None, *, allow_shrink: bool = False
) -> Path:
    """Write to data/raw/{name}.parquet, or data/raw/{name}/{season}.parquet
    when a season is given (per-season partitioning for game logs).

    The write is atomic. For the SHRINK_GUARDED season files, replacing a
    readable file with fewer rows raises ShrinkRefusedError and leaves the
    file alone, unless allow_shrink.
    """
    path = RAW_DIR / name / f"{season}.parquet" if season else RAW_DIR / f"{name}.parquet"
    if season and name in SHRINK_GUARDED and not allow_shrink:
        existing = parquet_row_count(path)
        if existing is not None and len(df) < existing:
            raise ShrinkRefusedError(
                f"{name}/{season}: the re-fetch has {len(df)} rows, the file on disk {existing}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(df, path)
    log.info(
        "Wrote %s (%d rows, %.1f KB)",
        path.relative_to(RAW_DIR),
        len(df),
        path.stat().st_size / 1024,
    )
    return path


def season_done(name: str, season: str) -> bool:
    """True when the season's file exists and reads as parquet. One that
    exists but doesn't read (say, from a write killed before writes were
    atomic) is logged and fetched again."""
    path = RAW_DIR / name / f"{season}.parquet"
    if is_valid_parquet(path):
        return True
    if path.exists():
        log.warning("%s/%s.parquet is unreadable - fetching it again", name, season)
    return False


def run(
    seasons: list[str],
    pbp_games: int | None,
    smoke_test: bool = False,
    force: bool = False,
    allow_shrink: bool = False,
) -> list[str]:
    """Ingest `seasons`. Returns the files the shrink guard refused to
    replace, as "name/season" - empty when everything was written."""
    latest = seasons[-1]
    refused: list[str] = []

    def save(df: pd.DataFrame, name: str, season: str | None = None) -> None:
        # Collected rather than raised, so one short answer doesn't stop the
        # rest of the run from landing.
        try:
            write_parquet(df, name, season, allow_shrink=allow_shrink)
        except ShrinkRefusedError as exc:
            log.error("%s - kept the existing file (rerun with --allow-shrink to accept)", exc)
            refused.append(f"{name}/{season}")

    if smoke_test:
        log.info("Smoke test: pulling team game logs for %s only", latest)
        df = fetch_team_game_logs(latest)
        if df.empty:
            raise SystemExit(f"Smoke test FAILED: no rows returned for {latest}")
        log.info(
            "Smoke test OK. Sample:\n%s",
            df[["GAME_DATE", "MATCHUP", "TEAM_ABBREVIATION", "PTS"]].head(),
        )
        return refused

    log.info("Ingesting %d season(s): %s .. %s", len(seasons), seasons[0], latest)
    team_logs_latest = None
    for i, season in enumerate(seasons, 1):
        # The latest season is always refreshed (it is still being played);
        # older seasons only fetch the datasets they are actually missing, so
        # adding a new dataset later does not re-pull everything else.
        stale = force or season == latest

        # stale and season are bound as defaults: needed() is only called
        # inside this iteration, but this keeps it safe if that ever changes.
        def needed(name: str, stale: bool = stale, season: str = season) -> bool:
            return stale or not season_done(name, season)

        wants_advanced = has_advanced_stats(season) and needed("player_advanced")
        # Schedule uses the same needed() gate as everything else, so it is
        # already covered by `stale`: the published schedule for the current
        # season changes (postponements, rescheduling), and `stale` is True
        # for the latest season regardless of what season_done() says. Do
        # not special-case it into always-fetch outside of needed() - that
        # would just duplicate the guarantee `stale` already gives.
        wants_schedule = needed("schedule")
        if not (
            needed("player_game_logs")
            or needed("team_game_logs")
            or wants_advanced
            or wants_schedule
        ):
            log.info("[%d/%d] %s already ingested - skipping", i, len(seasons), season)
            continue
        log.info("[%d/%d] %s", i, len(seasons), season)

        team_logs = None
        if needed("player_game_logs"):
            save(fetch_player_game_logs(season), "player_game_logs", season)
        if needed("team_game_logs"):
            team_logs = fetch_team_game_logs(season)
            save(team_logs, "team_game_logs", season)
        if wants_advanced:
            save(fetch_player_advanced(season), "player_advanced", season)
            save(fetch_team_advanced(season), "team_advanced", season)
        elif not has_advanced_stats(season):
            log.info(
                "  no official advanced stats before %s - dbt derives them from box scores instead",
                ADVANCED_FIRST_SEASON,
            )
        if wants_schedule:
            save(fetch_schedule(season), "schedule", season)
        if season == latest and team_logs is not None:
            team_logs_latest = team_logs

    # Play-by-play only for the latest requested season (1 API call per game).
    if pbp_games != 0:
        if team_logs_latest is None:
            team_logs_latest = pd.read_parquet(RAW_DIR / "team_game_logs" / f"{latest}.parquet")
        game_ids = (
            team_logs_latest.sort_values("GAME_DATE", ascending=False)["GAME_ID"]
            .drop_duplicates()
            .tolist()
        )
        if pbp_games is not None:
            game_ids = game_ids[:pbp_games]
        if not game_ids:
            # current_season() rolls over on October 1, about three weeks
            # before opening night. Until then the new season has no games,
            # and the last season's play-by-play already on disk stays put.
            log.info("No games played yet in %s - skipping play-by-play", latest)
        else:
            pbp = fetch_play_by_play(game_ids, latest)
            save(pbp, "play_by_play", latest)

    save(fetch_players(latest), "players")
    save(fetch_teams(), "teams")

    if refused:
        log.error("Ingestion finished, but kept the old file for: %s", ", ".join(refused))
    else:
        log.info("Ingestion complete. Raw parquet files are in %s", RAW_DIR)
    return refused


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--season",
        default=current_season(),
        help="Season string like 2025-26 (default: current season)",
    )
    parser.add_argument(
        "--backfill",
        metavar="START_SEASON",
        help="Ingest every season from START_SEASON (e.g. 1979-80) "
        "through --season. Existing seasons are skipped.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch seasons even if their files already exist"
    )
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help="Replace a season file even when the re-fetch has fewer rows",
    )
    parser.add_argument(
        "--pbp-games",
        type=int,
        default=20,
        help="Play-by-play: number of most recent games in the latest "
        "season (default: 20; 0 to skip)",
    )
    parser.add_argument(
        "--all-pbp",
        action="store_true",
        help="Pull play-by-play for every game in the latest season (slow)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Single small API call to verify connectivity, no files written",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    seasons = season_range(args.backfill, args.season) if args.backfill else [args.season]
    refused = run(
        seasons,
        None if args.all_pbp else args.pbp_games,
        smoke_test=args.smoke_test,
        force=args.force,
        allow_shrink=args.allow_shrink,
    )
    if refused:
        sys.exit(1)


if __name__ == "__main__":
    main()
