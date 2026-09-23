"""Ingest historical team payroll totals from Basketball-Reference.

For each team-season, fetches https://www.basketball-reference.com/teams/
{BBREF_CODE}/{END_YEAR}.html, sums the "Salaries Table" (id="salaries2") on
that page, and writes one row per team-season to data/raw/team_payroll/
{season}.parquet with columns:

    season, team_abbreviation, team_payroll, player_count

Every requested team gets a row, including one whose page has no salary
table at all (team_payroll null, player_count 0) - see ingest_season.

Basketball-Reference publishes a 20 requests/minute rate limit; this script
throttles to one request per 3.5 seconds (~17/min) to stay comfortably under
it. Do not remove the sleep.

Eight team codes differ between this project's nba_api-derived codes and
Basketball-Reference's own, with a different cutoff season - and in one case
a different direction - per franchise; see LEGACY_CODE_MAP, MODERN_CODE_MAP
and PERMANENT_CODE_MAP below, each with the live 200/404 pair that fixes its
boundary. Every other historical code, relocations included, matches directly.

Usage:
    python ingestion/team_payroll_ingest.py --season 2026-27

For a multi-season backfill use scripts/backfill_team_payroll.py, which is
what main() points you at - this module fetches one season per invocation.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "team_payroll"

MIN_SECONDS_BETWEEN_REQUESTS = 3.5
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# nba_code -> (bbref_code, last season-end-year still under that bbref_code).
# The first four also switched in nba_api's own codes at 1996-97, so their
# cutoff is a formality. WAS's is load-bearing: nba_api has used "WAS" across
# the franchise's entire history, but bbref published under "WSB" (Bullets)
# through 1996-97 and "WAS" (Wizards) only from the 1997-98 rename onward.
# Boundary verified live: WAS/1985.html 404, WSB/1985.html 200;
# WSB/1998.html 404, WAS/1998.html 200.
LEGACY_CODE_MAP = {
    "SAN": ("SAS", 1996),  # Spurs
    "GOS": ("GSW", 1996),  # Warriors
    "UTH": ("UTA", 1996),  # Jazz
    "PHL": ("PHI", 1996),  # 76ers
    "WAS": ("WSB", 1997),  # Bullets -> Wizards, renamed for 1997-98
}

# nba_code -> (bbref_code, first season-end-year under that bbref_code) - the
# mirror image of LEGACY_CODE_MAP: nba_api kept "CHA" through the 2014-15
# Bobcats-to-Hornets rename, bbref switched to "CHO" that same season.
# Boundary verified live: CHA/2014.html 200, CHO/2014.html 404;
# CHA/2015.html 404, CHO/2015.html 200.
MODERN_CODE_MAP = {
    "CHA": ("CHO", 2015),  # Bobcats -> Hornets
}

# Unlike the maps above, these two mismatches aren't era-limited: bbref has
# always published the Suns as "PHO" and the Nets (since the Brooklyn move)
# as "BRK", for every season this project's data covers.
# Verified live: PHX/1985.html 404, PHO/1985.html 200; PHX/2025.html 404,
# PHO/2025.html 200; BKN/2013.html 404, BRK/2013.html 200.
PERMANENT_CODE_MAP = {
    "PHX": "PHO",  # Suns
    "BKN": "BRK",  # Nets, since the 2012-13 Brooklyn move
}

log = logging.getLogger("team_payroll_ingest")
_last_request_at = 0.0

_SALARY_ROW_RE = re.compile(
    r'<td[^>]*data-append-csv="[^"]*"[^>]*data-stat="player"[^>]*><a[^>]*>([^<]+)</a></td>'
    r'<td[^>]*data-stat="salary"[^>]*csk="(\d+)"',
)


def season_end_year(season: str) -> int:
    """'1984-85' -> 1985, '1999-00' -> 2000, '2026-27' -> 2027."""
    start_year = int(season[:4])
    end_suffix = int(season[5:7])
    century = (start_year // 100) * 100
    end_year = century + end_suffix
    if end_year <= start_year:
        end_year += 100
    return end_year


def bbref_code(nba_code: str, season: str) -> str:
    """Map this project's team code to Basketball-Reference's, for the given season."""
    if nba_code in PERMANENT_CODE_MAP:
        return PERMANENT_CODE_MAP[nba_code]
    if nba_code in LEGACY_CODE_MAP:
        legacy_bbref_code, last_end_year = LEGACY_CODE_MAP[nba_code]
        if season_end_year(season) <= last_end_year:
            return legacy_bbref_code
    if nba_code in MODERN_CODE_MAP:
        modern_bbref_code, first_end_year = MODERN_CODE_MAP[nba_code]
        if season_end_year(season) >= first_end_year:
            return modern_bbref_code
    return nba_code


def parse_salary_table(html: str) -> list[dict]:
    """Extract [{'player': str, 'salary_usd': int}, ...] from a team-season page."""
    salaries_section = html.split('id="salaries2"', 1)
    if len(salaries_section) < 2:
        return []
    table_html = salaries_section[1]
    end = table_html.find("</table>")
    if end != -1:
        table_html = table_html[:end]
    return [
        {"player": player, "salary_usd": int(salary)}
        for player, salary in _SALARY_ROW_RE.findall(table_html)
    ]


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_at = time.monotonic()


def fetch_team_season_html(team_code: str, season: str) -> str:
    url = f"https://www.basketball-reference.com/teams/{team_code}/{season_end_year(season)}.html"
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            backoff = 2**attempt * 3
            log.warning("%s failed (attempt %d/%d): %s -- retrying in %ds",
                       url, attempt, MAX_RETRIES, exc, backoff)
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def team_season_payroll(nba_code: str, season: str) -> dict:
    """{'team_payroll': int|None, 'player_count': int} for one team-season.

    player_count is how many salary rows the total was built from, carried
    alongside the sum because a sum on its own can't say whether it came from a
    full roster or from the three players Basketball-Reference happens to have
    for that season. Two seasons in this backfill's range (1986-87 and 1989-90)
    are near-empty at the source, and some of their teams still sum to a
    plausible-looking fraction of that year's cap, so a cap-ratio heuristic
    alone misses them; the row count is a directly observed fact instead.

    team_payroll is None (never 0) when the page has no salary table - e.g. a
    franchise's first partial season, or one of the gap seasons above. A real
    team's payroll is never actually zero, so None can't be mistaken for a
    genuine value downstream.
    """
    code = bbref_code(nba_code, season)
    html = fetch_team_season_html(code, season)
    rows = parse_salary_table(html)
    if not rows:
        return {"team_payroll": None, "player_count": 0}
    return {"team_payroll": sum(r["salary_usd"] for r in rows), "player_count": len(rows)}


def ingest_season(season: str, team_codes: list[str]) -> pd.DataFrame:
    """Fetch payroll for every team active in `season` - one row per team, always.

    A team with no salary data still gets a row (null payroll, player_count 0)
    rather than being dropped: a downstream completeness flag can only fire for
    a team-season that actually exists in the data, so silently skipping one
    hides the gap instead of marking it.
    """
    records = []
    for code in team_codes:
        result = team_season_payroll(code, season)
        if result["player_count"] == 0:
            log.warning("No salary data for %s %s - writing a null-payroll row", code, season)
        records.append({
            "season": season,
            "team_abbreviation": code,
            "team_payroll": result["team_payroll"],
            "player_count": result["player_count"],
        })
    df = pd.DataFrame.from_records(
        records, columns=["season", "team_abbreviation", "team_payroll", "player_count"]
    )
    # Nullable Int64, not the float64 pandas would infer from the None rows -
    # payroll stays an exact integer in the parquet instead of picking up a
    # float type (and float formatting) just because some seasons have gaps.
    df["team_payroll"] = df["team_payroll"].astype("Int64")
    df["player_count"] = df["player_count"].astype("int64")
    return df


def write_season(season: str, team_codes: list[str], force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{season}.parquet"
    if out_path.exists() and not force:
        log.info("%s already ingested, skipping (use --force to redo)", season)
        return
    df = ingest_season(season, team_codes)
    df.to_parquet(out_path, index=False)
    empty = int((df["player_count"] == 0).sum())
    log.info("Wrote %s (%d teams, %d with no salary data)", out_path, len(df), empty)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", help="Single season, e.g. 2026-27")
    parser.add_argument("--backfill", metavar="START_SEASON",
                        help="Ingest every season from START_SEASON to the current season")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already ingested")
    parser.add_argument("--teams", nargs="+", required=True,
                        help="Team codes active this season (this project's nba_api codes)")
    args = parser.parse_args()

    if args.season:
        write_season(args.season, args.teams, force=args.force)
    elif args.backfill:
        raise SystemExit(
            "Per-season --teams differs by era (relocations/expansion) - run the "
            "one-time backfill via scripts/backfill_team_payroll.py (Task 3), not "
            "this flag directly."
        )
    else:
        parser.error("Pass --season or --backfill")


if __name__ == "__main__":
    main()
