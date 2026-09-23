"""Ingest historical team payroll totals from Basketball-Reference.

For each team-season, fetches https://www.basketball-reference.com/teams/
{BBREF_CODE}/{END_YEAR}.html, sums the "Salaries Table" (id="salaries2") on
that page, and writes one row per team-season to data/raw/team_payroll/
{season}.parquet.

Basketball-Reference publishes a 20 requests/minute rate limit; this script
throttles to one request per 3.5 seconds (~17/min) to stay comfortably under
it. Do not remove the sleep.

Six team codes differ between this project's nba_api-derived codes and
Basketball-Reference's own codes for part of their history (Spurs, Warriors,
Jazz, 76ers, Bullets/Wizards, Bobcats/Hornets) - see LEGACY_CODE_MAP below;
each entry's own cutoff season controls when the remap applies, since that
cutoff isn't the same for every franchise, and the direction differs too:
four switched away from a bbref-only code at 1996-97 (nba_api never emits
those codes after that season, so the cutoff is a formality); Washington's
Bullets-to-Wizards rename, and Basketball-Reference's matching code change,
didn't happen until 1997-98, and nba_api never changed WAS's own code at
all; Charlotte is the mirror image of the other four - nba_api has used
"CHA" for this franchise continuously across the 2004 expansion and the
2014-15 Bobcats-to-Hornets rename, but Basketball-Reference switched to
"CHO" starting with the 2014-15 season, so the remap only starts applying
partway through this one's history rather than ending partway through.
Two more codes differ across every era, not just historically (Suns:
nba_api's "PHX" vs Basketball-Reference's "PHO"; Nets since the Brooklyn
move: nba_api's "BKN" vs Basketball-Reference's "BRK") - see
PERMANENT_CODE_MAP below. Every other historical code, including relocated
franchises, matches directly.

Usage:
    python ingestion/team_payroll_ingest.py --season 2026-27
    python ingestion/team_payroll_ingest.py --backfill 1984-85   # every season from 1984-85 to now
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
# The first four switched in nba_api's own codes at the 1996-97 season (nba_api
# never emits "SAN" etc. after that season, so the cutoff here is a formality).
# WAS is different: nba_api has used "WAS" for this franchise across its
# entire history, but Basketball-Reference published pages under "WSB"
# (Bullets) through the 1996-97 season and "WAS" (Wizards) only from the
# 1997-98 rename onward - confirmed live (basketball-reference.com/teams/
# WAS/1985.html 404s, WSB/1985.html 200s; WSB/1998.html 404s, WAS/1998.html
# 200s), discovered when the real backfill (Task 3) crashed on a 404 for
# WAS/1985.html.
LEGACY_CODE_MAP = {
    "SAN": ("SAS", 1996),  # Spurs
    "GOS": ("GSW", 1996),  # Warriors
    "UTH": ("UTA", 1996),  # Jazz
    "PHL": ("PHI", 1996),  # 76ers
    "WAS": ("WSB", 1997),  # Bullets -> Wizards, renamed for 1997-98
}

# nba_code -> (bbref_code, first season-end-year under that bbref_code).
# The mirror image of LEGACY_CODE_MAP: nba_api kept "CHA" through the 2014-15
# Bobcats-to-Hornets rename, but Basketball-Reference switched to "CHO" that
# same season - confirmed live (basketball-reference.com/teams/CHA/2015.html
# 404s, CHO/2015.html 200s; CHA/2014.html 200s, CHO/2014.html 404s), found
# the same way as WAS/PHX below: the real backfill (Task 3) would have
# crashed on this the moment it reached a post-2014-15 Hornets season.
MODERN_CODE_MAP = {
    "CHA": ("CHO", 2015),  # Bobcats -> Hornets, Basketball-Reference's code changed for 2014-15
}

# Unlike the codes above, these two mismatches aren't era-limited at all:
# nba_api has used "PHX" for the Suns and "BKN" for the Nets (since the
# Brooklyn move) across their entire respective histories in this project's
# data, but Basketball-Reference has always published under "PHO" and "BRK"
# - confirmed live (.../PHX/*.html and .../BKN/*.html 404 for every season
# checked; .../PHO/*.html and .../BRK/*.html 200), discovered when the real
# backfill (Task 3) crashed on 404s for PHX/1985.html and BKN/2013.html.
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


def team_season_payroll(nba_code: str, season: str) -> int | None:
    """Total payroll for one team-season, or None if the page has no salary table
    (e.g. a franchise's first partial season, or a season Basketball-Reference has
    no salary data for)."""
    code = bbref_code(nba_code, season)
    html = fetch_team_season_html(code, season)
    rows = parse_salary_table(html)
    if not rows:
        return None
    return sum(r["salary_usd"] for r in rows)


def ingest_season(season: str, team_codes: list[str]) -> pd.DataFrame:
    """Fetch payroll for every team active in `season`, skipping teams with no data."""
    records = []
    for code in team_codes:
        total = team_season_payroll(code, season)
        if total is None:
            log.warning("No salary data for %s %s - skipping", code, season)
            continue
        records.append({"season": season, "team_abbreviation": code, "team_payroll": total})
    return pd.DataFrame.from_records(records, columns=["season", "team_abbreviation", "team_payroll"])


def write_season(season: str, team_codes: list[str], force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{season}.parquet"
    if out_path.exists() and not force:
        log.info("%s already ingested, skipping (use --force to redo)", season)
        return
    df = ingest_season(season, team_codes)
    df.to_parquet(out_path, index=False)
    log.info("Wrote %s (%d teams)", out_path, len(df))


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
