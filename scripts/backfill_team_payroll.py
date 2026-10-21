"""One-time historical backfill of team payroll, 1984-85 through the current season.

Derives which team codes were active each season from this project's own
warehouse - see scripts/season_teams.py - rather than hand-maintaining a
separate relocation table here.

Usage:
    python scripts/backfill_team_payroll.py
    python scripts/backfill_team_payroll.py --force   # re-fetch already-ingested seasons too

Exits 1 after the last season if any season was left incomplete (a team
failed, or the shrink guard kept the old files); the log names them. A
season missing a team is fetched again by a plain rerun.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT))
from ingestion.team_payroll_ingest import write_season
from scripts.season_teams import seasons_and_teams

log = logging.getLogger("backfill_team_payroll")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    by_season = seasons_and_teams()
    log.info("Backfilling %d seasons (%s -> %s)", len(by_season), min(by_season), max(by_season))
    # Every season is attempted even after one fails, so a single bad team
    # doesn't leave the rest of the history unfetched.
    incomplete = [
        season
        for season, teams in by_season.items()
        if not write_season(season, teams, force=args.force)
    ]
    if incomplete:
        # Which teams failed is in each season's own error line above.
        log.error(
            "Backfill finished with %d incomplete season(s): %s",
            len(incomplete),
            ", ".join(incomplete),
        )
        sys.exit(1)
    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
