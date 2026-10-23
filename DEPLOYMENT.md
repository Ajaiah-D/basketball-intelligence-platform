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
   Open **Advanced settings** and set **Python version** to **3.12**, the
   version the lock files are compiled for. It can't be changed later
   without deleting and redeploying the app (see "Python version on
   Streamlit Cloud" below).

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

## Shipping a code change

Push to `main`, wait for the Tests workflow to pass, then open the live app
and check the change is there. Community Cloud is supposed to redeploy on
every push, but this app has repeatedly kept serving the previous code
(three times in September-October 2026). When that happens: share.streamlit.io,
the app's **⋮** menu, **Reboot app**. A reboot also re-downloads the
warehouse. If reboots stop working, delete the app and recreate it from the
same repo with the same secrets and custom subdomain.

Community Cloud installs `requirements.txt`, the runtime lock file, so the
app gets exactly the package versions CI tested. A dependency change is a
lock file change (see [CONTRIBUTING.md](CONTRIBUTING.md)) and reaches the app
with the push that carries it. The dev-only packages (pytest, scikit-learn,
scipy, the linters) are in `requirements-dev.txt` and never installed there,
which is why the dashboard must not import `ml/` or `scripts/`.

A change that needs new data (a new dbt model, seed or column) is not live
until the warehouse is republished too: run `python scripts/weekly_refresh.py`
once after pushing, or wait for the next scheduled run. Pages are written to
keep working against an older warehouse in the meantime, and warehouse
changes are additive until the code that reads them has shipped (the
"expand, then contract" rule in CONTRIBUTING.md).

## Python version on Streamlit Cloud

The app must run Python 3.12 to match the lock files. Community Cloud fixes
an app's Python version when the app is created: the app's settings show
it, but changing it means deleting the app and deploying it again.

To check it: share.streamlit.io, the app's **⋮** menu, **Settings**. The
Python version is listed there and can't be edited.

To change it, delete and redeploy with the same address and secrets:

1. In the app's **Settings**, open **Secrets** and copy the whole text
   somewhere safe outside the repo. Deleting the app deletes its secrets.
2. Note the app's address: `basketball-intelligence-platform` in
   `https://basketball-intelligence-platform.streamlit.app`.
3. From the app's **⋮** menu, choose **Delete** and confirm.
4. Create the app again ("New app"): the same repo, branch `main`, main
   file path `dashboard/app.py`, and the same subdomain as the **App URL**
   (it is free again once the old app is gone).
5. Open **Advanced settings**, set **Python version** to **3.12**, and paste
   the secrets back in.
6. Deploy. The first boot downloads the warehouse. Then open the public
   address and check a few pages; if it returns a 404, the subdomain didn't
   attach, so set it again in the app's settings.

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
    (Next.js + FastAPI reusing the `dashboard/lib/data/` queries) pays off.
- **Data refresh cadence**: `scripts/weekly_refresh.py` runs the pipeline
  end to end (ingest game data, load DuckDB, scrape the current season's
  salaries, dbt build, re-score player impact for the Arcade, predict
  and score games, republish to the `data-v1` Release) and is meant to be triggered by a local Windows Task Scheduler job, not
  GitHub Actions. stats.nba.com silently blocks requests from cloud/
  datacenter IP ranges (AWS, Azure, GCP, and GitHub-hosted Actions runners
  all fall in that bucket, confirmed by a failed test run: every request
  timed out from GitHub's network but worked instantly from a home IP), so
  the ingestion step has to run from a real residential connection. The
  live app checks a version marker next to the Release asset hourly and
  re-downloads on its own when it changes, so new *data* needs no manual
  reboot (new *code* sometimes does - see "Shipping a code change" above).
  Two steps are allowed to fail without stopping the run: the salary scrape
  and the player impact scoring. The rest of the refresh still publishes
  (the warehouse keeps last week's salary or impact tables), and each
  failure is recorded in the run log (`payroll_ok`, `player_impact_ok`).

  The warehouse is built in a copy (`warehouse/next/basketball.duckdb`) and
  only swapped onto `basketball.duckdb` once every required step passed, so
  a failed run leaves the real file and the release untouched. The swap
  retries for about 20 seconds, then fails if something still holds the
  warehouse open (a local dashboard): close it and rerun.

  Publishing uploads the warehouse first and `version.txt` second.
  `version.txt` is written only after the warehouse upload succeeded,
  because the live app re-downloads when that marker changes and must never
  be told about data that isn't there yet. If the marker's own upload fails,
  the local file is put back and the run counts as failed; running apps
  stay on the old data until the next good run.

  New predictions go to `data/predictions/history.csv`, which the run
  commits with its log. Only a run that uploaded the warehouse keeps them:
  any other ending puts the file back as the run found it. So if the swap
  succeeds but `publish_release` fails, the local warehouse is already the
  new one, with that run's predictions in its table, while `history.csv` is
  rolled back; the release's warehouse asset and `version.txt` are
  untouched. The next run's load rebuilds `main.predictions` from the CSV,
  so the two agree again.

  Logs:
  - `logs/refresh_runs.jsonl`: one line per run (committed; see "Checking
    data health" below).
  - `logs/runs/<run time>/`: the refresh's own messages (`refresh.log`)
    and each step's full output. Look here first when a step failed.
  - `logs/refresh.log`: one line per launch, including launches that found
    another run going and did nothing.
  - `logs/refresh.lock`: held while a run is going, so two runs can't
    overlap. A lock older than 6 hours is taken to be left by a killed run
    and is taken over.

  Before a scheduled run, and after any change to the pipeline,
  `python scripts/weekly_refresh.py --no-publish` does a dry run: every step
  against the copy, then the copy is deleted - no swap, upload or commit,
  and no rows added to the predictions history. It does still update the
  raw parquet files and `data/last_updated.json`, and logs a
  `"dry_run": true` line (which `health_check.py` skips); the next
  scheduled run commits both.

  **Where the data lives.** The refresh machine's `.env` sets
  `BIP_DATA_HOME` to a folder outside OneDrive, because sync can lock or
  half-upload a 90 MB file while it is being written, which breaks the
  swap. The raw parquet files (`raw/`) and the warehouse (`warehouse/`)
  live under that folder. The run logs, the predictions history and the
  test fixtures stay in the repo, because they are committed. Without the
  variable everything stays under the repo, as before.

  It's registered as a Windows Scheduled Task named
  `BasketballIntelligence-WeeklyRefresh` (action: this repo's
  `.venv\Scripts\python.exe scripts\weekly_refresh.py`, working directory
  the repo root). That `.venv` is Python 3.12, installed from the lock
  files like any other checkout (see the README's Setup). **This task lives in Windows, not in git** - nothing in
  the repo controls whether it's enabled, paused, or what time it fires.
  Checking or changing it requires a shell on the machine it's registered
  on (currently the user's desktop PC, always on):
  ```powershell
  Get-ScheduledTask -TaskName "BasketballIntelligence-WeeklyRefresh" | Get-ScheduledTaskInfo
  # Change the trigger (e.g. re-pausing for the offseason, or a new time):
  Set-ScheduledTask -TaskName "BasketballIntelligence-WeeklyRefresh" -Trigger (
      New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At "2026-10-13T06:00:00")
  ```
  **Current state (as of 2026-10-13):** running weekly, Tuesdays at 6 AM.
  It was paused over the 2026 offseason by pushing the trigger's start
  boundary to 2026-10-13, and resumed itself on that date as intended
  (`logs/refresh_runs.jsonl` has the run). To pause it again next summer,
  push the start boundary forward the same way rather than disabling the
  task, so it resumes with no follow-up.

  Between October 1 and opening night the new season exists but has no
  games. The refresh handles that: it skips play-by-play, and the salary
  step keeps using the last season that has games.

  If this ever moves to a new machine (e.g. a mini PC), the Scheduled
  Task has to be recreated there; nothing about it migrates with `git
  clone`. Neither does the data: copy the `BIP_DATA_HOME` folder across
  (or backfill again) and set the same variable in that machine's `.env`,
  then do a dry run before the first scheduled one.

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
