# 0004. Local Task Scheduler over GitHub Actions for the data refresh

**Status:** Accepted

## Context

The weekly data refresh (ingest, DuckDB, dbt, republish to the `data-v1`
release) needs to run on a schedule without manual intervention. A GitHub
Actions workflow (`.github/workflows/refresh-data.yml`) was built and run
in production across commits `22f7850` through `94a69ea`. It was then
deleted after stats.nba.com was found to silently block requests from
cloud and datacenter IP ranges, GitHub-hosted runners included - confirmed
by a failed test run: every request timed out from GitHub's network but
worked instantly from a home IP (`DEPLOYMENT.md:72-78`).

## Decision

Run `scripts/weekly_refresh.py` as a Windows Scheduled Task
(`BasketballIntelligence-WeeklyRefresh`) on the user's desktop machine
instead of in CI, since the ingestion step needs to originate from a real
residential IP address.

## Consequences

This makes the refresh actually work, since stats.nba.com accepts the
traffic. It also means the refresh has no CI-grade guarantees: it runs
outside git, its schedule and enabled/paused state are not tracked in the
repo, and the pipeline now depends on one specific always-on machine being
on, connected, and correctly configured. That dependency, and its lack of
alerting, is documented in full in `0006-known-limitations.md` rather than
repeated here. This would be revisited if a residential-IP-equivalent path
reachable from CI became available (a proxy or VPN exit node on a
residential range), or if the data source stopped being IP-restricted.
