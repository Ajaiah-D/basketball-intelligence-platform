# 0006. Known limitations

**Status:** Accepted

## Context

Some limitations follow from earlier decisions in this platform and are
easy to lose track of once the system is working day to day: where the
refresh pipeline physically runs, what the data source's terms allow, and
a few gaps in the data and the prediction model that were found and
recorded rather than fixed. All are worth stating plainly rather than
leaving implicit, since they bound what can be safely promised about this
system's reliability, its numbers and its future business use.

## Decision

Record these limitations explicitly as accepted, known constraints of the
current architecture:

1. **Single-desktop dependency.** The weekly refresh only runs if one
   specific Windows machine is on, connected, and has the Scheduled Task
   enabled (see `0004-local-task-scheduler-over-github-actions.md`) - there
   is no redundancy, and nothing in the repo alerts anyone if a refresh
   silently stops happening. `data/last_updated.json` and
   `logs/refresh_runs.jsonl` record outcomes, and `scripts/health_check.py`
   reports on them, but only when someone runs it. Losing that machine
   pauses all data freshness until it is restored or the pipeline is moved
   elsewhere.

2. **Monetization is constrained by the data source's terms, not by a
   formal license.** The data comes from stats.nba.com, an *unofficial*
   API accessed via `nba_api` (`README.md`, "Data sources") - there is no data license,
   formal or informal, only the general expectation that heavy or
   commercial use of an unofficial, throttled endpoint is not what it is
   meant for (`DEPLOYMENT.md`, "Capacity and the monetization path": "Terms allow hobby/portfolio use; it is
   not meant for a commercial product"). This is a real constraint on any
   future monetization plan, but it is a terms-of-use risk to manage, not
   a licensing agreement to renegotiate.

3. **One conference per team-code era.** The `team_codes` seed gives each
   era of a code one conference
   (`0011-shared-core-package-and-team-codes-seed.md`), so the few
   realignments that happened within an era show the code's later
   conference: the New Orleans Hornets (`NOH`) played in the East in
   2002-03 and 2003-04 but are listed in the West, and in 1979-80 Milwaukee
   (then West) and Houston and San Antonio (then East) are listed in their
   later conferences. Standings and conference views for those seasons are
   wrong for those teams.

4. **The prediction model's calibration has two measured flaws.** The
   published win probabilities turn a predicted margin into a probability
   with a spread (`PREDICTION_MARGIN_SD` in `core/constants.py`) of 13.5
   points, while the walk-forward backtest's log-loss optimum is about
   12.0. The cost is small (log loss 0.6168 against 0.6160), but the
   probabilities are a little too cautious. On the same holdout the model
   also over-predicts the home side's margin by about 1.1 points. Both were
   measured on 2026-10-22 and left unchanged: changing either changes every
   published probability, so it needs its own decision and a new
   `model_version`.

5. **Play-by-play only accumulates from October 2026 on.** Each refresh
   now adds the season's games it doesn't hold yet (up to 120 a run).
   Before that, the file was overwritten every week with the most recent
   games, so only a handful of earlier games have play-by-play, and the
   rest have no game-flow or shot chart on the Games page. They were not
   backfilled: `ingestion/nba_ingest.py --all-pbp` can do it, at about
   1,300 API calls per season.

6. **The settled-predictions query exists twice until the next publish.**
   `mart_settled_predictions` is newer than the published warehouse, so the
   dashboard keeps an identical copy of its SQL
   (`dashboard/lib/data/predictions.py`), held equal by
   `tests/test_settled_predictions.py`. This is the open contract step in
   `0008-dbt-marts-as-the-single-source-of-truth.md`.

## Consequences

Writing these down makes the operational, data and business risk profile
visible to anyone reasoning about this system's reliability or its future,
instead of leaving them as tribal knowledge. It also commits them to a
permanent record as accepted debt rather than problems already being worked
on.

For limitation 1, this would be resolved by adding staleness alerting on
`data/last_updated.json` / `logs/refresh_runs.jsonl`, or by moving the
refresh off the single desktop once a residential-IP-equivalent path
reachable from another host exists. For limitation 2, this would need to
be revisited only if the platform pursued a genuinely commercial use,
which would mean evaluating an official or licensed data provider rather
than continuing on an unofficial endpoint's implicit tolerance.

Limitation 3 is fixed by splitting the affected codes' rows in
`team_codes.csv` by season, which visibly changes old standings.
Limitation 4 is a model change: refit the spread and the home edge, bump
`model_version`, and let the track record show the new version
separately. Limitation 5 is a backfill run, limited by the API's rate
rather than by code. Limitation 6 ends on its own schedule: once a refresh
has published the mart, the dashboard reads it, and the copy and its
equality test are deleted.
