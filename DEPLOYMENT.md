# Deploying the dashboard publicly (free)

Recommended path: **Streamlit Community Cloud**. Free, no port forwarding,
HTTPS included, deploys straight from GitHub, handles a fair amount of
casual traffic. When monetization arrives, the included `Dockerfile` moves
the exact same app to a paid host (Render / Fly.io / Railway) without code
changes.

## One-time setup (steps only you can do)

1. **Push the repo to GitHub** (public or private both work):
   ```
   git remote add origin https://github.com/<you>/basketball-intelligence-platform.git
   git push -u origin main
   ```

2. **Publish the warehouse file as a Release asset** (it is gitignored and
   too large for normal git). Check the size first, GitHub Release assets
   allow up to 2 GB:
   ```
   gh release create data-v1 warehouse/basketball.duckdb --title "Warehouse" --notes "Kept up to date by scripts/weekly_refresh.py"
   ```
   Copy the asset's download URL. The `data-v1` tag is reused for every
   future refresh (see below), so the URL you paste into the secret below
   never has to change again.
   (If you prefer not to use Releases: Cloudflare R2 has a free 10 GB tier;
   any URL that serves the file works, but the refresh script below
   assumes a GitHub Release.)

3. **Create the app** at https://share.streamlit.io. Sign in with GitHub,
   "New app", pick the repo, set **Main file path** to `dashboard/app.py`.

4. **Set secrets** (app, then Settings, then Secrets). This replaces `.env`
   in the cloud. Never commit either:
   ```toml
   WAREHOUSE_URL = "https://github.com/<you>/<repo>/releases/download/data-v1/basketball.duckdb"

   # Either hide the Dev Lab entirely on the public app (recommended):
   DEV_LAB_ENABLED = "false"
   # ...or keep it and set a strong password you have NOT shared anywhere:
   # DEV_PASSWORD = "<long-random-string>"
   ```

5. Deploy. First boot downloads the warehouse (spinner shows), then it's
   cached on disk for subsequent runs.

## Security checklist for going public

- [ ] `.env` was never committed (`git log --all --oneline -- .env` shows nothing)
- [ ] Rotate `DEV_PASSWORD` to a fresh value before deploying; the old one
      existed on your dev machine
- [ ] `DEV_LAB_ENABLED = "false"` on the public app (SQL access stays local)
- [ ] Dependabot alerts enabled on the GitHub repo (Settings, Security)
- [ ] Occasionally: `pip-audit` against requirements.txt

## Capacity and the monetization path

- **Community Cloud** (free): fine for portfolio traffic and friends.
  Roughly dozens of concurrent users; ~2.7 GB RAM; the app sleeps after
  inactivity and wakes on visit. Terms allow hobby/portfolio use; it is
  not meant for a commercial product.
- **When money enters**: use the `Dockerfile`.
  - Render (from ~$7/mo) or Fly.io (from ~$5/mo): always-on, custom domain,
    env-var secrets, horizontal scale later.
  - Put Cloudflare (free) in front for CDN/DDoS + custom domain TLS.
  - Payments: Stripe Checkout links work fine from a Streamlit app; full
    accounts/subscriptions are the point where a custom frontend
    (Next.js + FastAPI reusing `dashboard/lib/db.py` queries) pays off.
- **Data refresh cadence**: `scripts/weekly_refresh.py` runs the pipeline
  end to end (ingest, DuckDB, dbt, republish to the `data-v1` Release) and
  is meant to be triggered by a local Windows Task Scheduler job, not
  GitHub Actions. stats.nba.com silently blocks requests from cloud/
  datacenter IP ranges (AWS, Azure, GCP, and GitHub-hosted Actions runners
  all fall in that bucket, confirmed by a failed test run: every request
  timed out from GitHub's network but worked instantly from a home IP), so
  the ingestion step has to run from a real residential connection. The
  live app checks a version marker next to the Release asset hourly and
  re-downloads on its own when it changes, no manual reboot needed.

  It's registered as a Windows Scheduled Task named
  `BasketballIntelligence-WeeklyRefresh` (action: this repo's
  `.venv\Scripts\python.exe scripts\weekly_refresh.py`, working directory
  the repo root). **This task lives in Windows, not in git** - nothing in
  the repo controls whether it's enabled, paused, or what time it fires.
  Checking or changing it requires a shell on the machine it's registered
  on (currently the user's desktop PC, always on):
  ```powershell
  Get-ScheduledTask -TaskName "BasketballIntelligence-WeeklyRefresh" | Get-ScheduledTaskInfo
  # Change the trigger (e.g. re-pausing for the offseason, or a new time):
  Set-ScheduledTask -TaskName "BasketballIntelligence-WeeklyRefresh" -Trigger (
      New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At "2026-10-13T06:00:00")
  ```
  **Current state (set 2026-07-13):** paused for the offseason - the
  weekly Tuesday 6 AM trigger's start boundary is pushed to
  **2026-10-13** (second week of October, ahead of the 2026-27 season
  opener), so it won't fire again until then. It stayed *enabled* rather
  than disabled specifically so it resumes itself with no follow-up
  needed - update the date above if the actual season start differs.

  If this ever moves to a new machine (e.g. a mini PC), the Scheduled
  Task has to be recreated there; nothing about it migrates with `git
  clone`.

## Checking data health

`python scripts/health_check.py` reports whether the warehouse exists, row
counts look sane, the most recent game isn't stale, whether the last
scheduled run succeeded, and (unless `--skip-api`) whether stats.nba.com
is still responding the way the ingestion script expects. Run it any time,
or hand it to an AI assistant pointed at this repo and ask it to check the
data's health.

For a quick glance without pulling the full warehouse: `weekly_refresh.py`
commits `data/last_updated.json` (timestamp, season range, row counts) and
`logs/refresh_runs.jsonl` (one JSON line per run: per-step ok/fail, timing,
error tail on failure) back to the repo after every run. Both are plain
git history, readable with `gh api
repos/<you>/<repo>/contents/data/last_updated.json`, `git log --
logs/refresh_runs.jsonl`, or a local checkout, no GitHub Actions or
always-on service required.
