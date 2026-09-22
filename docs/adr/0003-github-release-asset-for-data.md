# 0003. GitHub Release asset for the warehouse file

**Status:** Accepted

## Context

`warehouse/basketball.duckdb` is regenerated in full by every weekly
refresh and is gitignored (`warehouse/*.duckdb`, `warehouse/*.duckdb.wal`)
rather than committed. Git is a poor fit for an ~92 MB binary that fully
replaces itself on every run: every refresh would add another full copy to
repo history with no way to diff or shrink it, and the cloud-hosted
dashboard still needs some way to obtain the file at boot since it is not
in the repo it deploys from.

## Decision

Publish the warehouse file as a GitHub Release asset instead, under the
`data-v1` tag. The tag is reused indefinitely across refreshes rather than
cut fresh each time (`scripts/weekly_refresh.py:29`), so the download URL
configured in the app's `WAREHOUSE_URL` secret never has to change
(`DEPLOYMENT.md:21-36`). The live app downloads the asset on first boot and
re-checks it hourly via `bootstrap_warehouse()` in `dashboard/app.py`,
comparing against a small `version.txt` published alongside it so a fresh
refresh reaches the app without a manual redeploy.

## Consequences

This keeps the git repo small and fast regardless of how many refreshes
have run, and gives a stable, unchanging download URL for the cloud
deployment. It costs a real download on cold boot (the full file, over
HTTP) and means the warehouse's history is not versioned the way committed
files are - only the current release asset is kept, not a diffable history
of every past state of the data. Publishing a new version also requires
release-write access (the `gh` CLI authenticated as the repo owner), which
only the machine running the weekly refresh has. This would need to change
if the warehouse ever needed to be queried without first being downloaded
whole, or if past states of the data needed to be recoverable.
