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
retry with exponential backoff. Do not remove the sleeps.

Game logs are written one parquet per season (data/raw/player_game_logs/
{season}.parquet), so multi-season backfills are resumable: seasons whose
files already exist are skipped unless --force is passed.

Usage:
    python ingestion/nba_ingest.py                      # current season, 20 most recent games of PBP
    python ingestion/nba_ingest.py --season 2025-26 --pbp-games 50
    python ingestion/nba_ingest.py --backfill 1979-80   # everything from 1979-80 to now
    python ingestion/nba_ingest.py --all-pbp            # every game (slow: ~1300 calls)
    python ingestion/nba_ingest.py --smoke-test         # tiny pull to verify the API works
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import (
    commonallplayers,
    leaguedashplayerstats,
    leaguedashteamstats,
    leaguegamelog,
    playbyplayv3,
    scheduleleaguev2,
)
from nba_api.stats.static import teams as static_teams

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# The NBA only publishes advanced box score stats (ratings, usage, PIE) from
# 1996-97 on; earlier seasons return zero rows. Everything before that is
# covered by the metrics dbt derives from raw box scores instead.
ADVANCED_FIRST_SEASON = "1996-97"

# --- Rate limiting -----------------------------------------------------------
# stats.nba.com has no published limits; community experience is that bursts
# get you temporarily blocked. Keep >= 1.5s between requests.
MIN_SECONDS_BETWEEN_REQUESTS = 1.5
REQUEST_TIMEOUT = 60
MAX_RETRIES = 4

log = logging.getLogger("nba_ingest")
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_at = time.monotonic()


def call_endpoint(endpoint_cls, **kwargs) -> pd.DataFrame:
    """Call an nba_api endpoint with throttling and exponential backoff.

    Returns the endpoint's first result set as a DataFrame.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            result = endpoint_cls(timeout=REQUEST_TIMEOUT, **kwargs)
            return result.get_data_frames()[0]
        except Exception as exc:  # network errors, JSON decode on throttle pages, etc.
            if attempt == MAX_RETRIES:
                raise
            backoff = 2**attempt * 2  # 4s, 8s, 16s
            log.warning(
                "%s failed (attempt %d/%d): %s -- retrying in %ds",
                endpoint_cls.__name__, attempt, MAX_RETRIES, exc, backoff,
            )
            time.sleep(backoff)
    raise RuntimeError("unreachable")


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
    log.info("Fetching play-by-play for %d games (rate limited, ~%.0fs minimum) ...",
             len(game_ids), len(game_ids) * MIN_SECONDS_BETWEEN_REQUESTS)
    frames = []
    for i, game_id in enumerate(game_ids, 1):
        try:
            df = call_endpoint(playbyplayv3.PlayByPlayV3, game_id=game_id)
        except Exception as exc:
            log.error("  giving up on game %s after retries: %s", game_id, exc)
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

def write_parquet(df: pd.DataFrame, name: str, season: str | None = None) -> Path:
    """Write to data/raw/{name}.parquet, or data/raw/{name}/{season}.parquet
    when a season is given (per-season partitioning for game logs)."""
    if season:
        path = RAW_DIR / name / f"{season}.parquet"
    else:
        path = RAW_DIR / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    log.info("Wrote %s (%d rows, %.1f KB)",
             path.relative_to(RAW_DIR), len(df), path.stat().st_size / 1024)
    return path


def season_done(name: str, season: str) -> bool:
    return (RAW_DIR / name / f"{season}.parquet").exists()


def run(seasons: list[str], pbp_games: int | None, smoke_test: bool = False,
        force: bool = False) -> None:
    latest = seasons[-1]
    if smoke_test:
        log.info("Smoke test: pulling team game logs for %s only", latest)
        df = fetch_team_game_logs(latest)
        if df.empty:
            raise SystemExit(f"Smoke test FAILED: no rows returned for {latest}")
        log.info("Smoke test OK. Sample:\n%s",
                 df[["GAME_DATE", "MATCHUP", "TEAM_ABBREVIATION", "PTS"]].head())
        return

    log.info("Ingesting %d season(s): %s .. %s", len(seasons), seasons[0], latest)
    team_logs_latest = None
    for i, season in enumerate(seasons, 1):
        # The latest season is always refreshed (it is still being played);
        # older seasons only fetch the datasets they are actually missing, so
        # adding a new dataset later does not re-pull everything else.
        stale = force or season == latest

        def needed(name: str) -> bool:
            return stale or not season_done(name, season)

        wants_advanced = has_advanced_stats(season) and needed("player_advanced")
        # Schedule uses the same needed() gate as everything else, so it is
        # already covered by `stale`: the published schedule for the current
        # season changes (postponements, rescheduling), and `stale` is True
        # for the latest season regardless of what season_done() says. Do
        # not special-case it into always-fetch outside of needed() - that
        # would just duplicate the guarantee `stale` already gives.
        wants_schedule = needed("schedule")
        if not (needed("player_game_logs") or needed("team_game_logs") or wants_advanced
                or wants_schedule):
            log.info("[%d/%d] %s already ingested - skipping", i, len(seasons), season)
            continue
        log.info("[%d/%d] %s", i, len(seasons), season)

        team_logs = None
        if needed("player_game_logs"):
            write_parquet(fetch_player_game_logs(season), "player_game_logs", season)
        if needed("team_game_logs"):
            team_logs = fetch_team_game_logs(season)
            write_parquet(team_logs, "team_game_logs", season)
        if wants_advanced:
            write_parquet(fetch_player_advanced(season), "player_advanced", season)
            write_parquet(fetch_team_advanced(season), "team_advanced", season)
        elif not has_advanced_stats(season):
            log.info("  no official advanced stats before %s - dbt derives them "
                     "from box scores instead", ADVANCED_FIRST_SEASON)
        if wants_schedule:
            write_parquet(fetch_schedule(season), "schedule", season)
        if season == latest and team_logs is not None:
            team_logs_latest = team_logs

    # Play-by-play only for the latest requested season (1 API call per game).
    if pbp_games != 0:
        if team_logs_latest is None:
            team_logs_latest = pd.read_parquet(
                RAW_DIR / "team_game_logs" / f"{latest}.parquet")
        game_ids = (
            team_logs_latest.sort_values("GAME_DATE", ascending=False)["GAME_ID"]
            .drop_duplicates()
            .tolist()
        )
        if pbp_games is not None:
            game_ids = game_ids[:pbp_games]
        pbp = fetch_play_by_play(game_ids, latest)
        write_parquet(pbp, "play_by_play", latest)

    write_parquet(fetch_players(latest), "players")
    write_parquet(fetch_teams(), "teams")

    log.info("Ingestion complete. Raw parquet files are in %s", RAW_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", default=current_season(),
                        help="Season string like 2025-26 (default: current season)")
    parser.add_argument("--backfill", metavar="START_SEASON",
                        help="Ingest every season from START_SEASON (e.g. 1979-80) "
                             "through --season. Existing seasons are skipped.")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch seasons even if their files already exist")
    parser.add_argument("--pbp-games", type=int, default=20,
                        help="Play-by-play: number of most recent games in the latest "
                             "season (default: 20; 0 to skip)")
    parser.add_argument("--all-pbp", action="store_true",
                        help="Pull play-by-play for every game in the latest season (slow)")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Single small API call to verify connectivity, no files written")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    seasons = (season_range(args.backfill, args.season) if args.backfill
               else [args.season])
    run(seasons, None if args.all_pbp else args.pbp_games,
        smoke_test=args.smoke_test, force=args.force)


if __name__ == "__main__":
    main()
