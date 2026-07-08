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
   gh release create data-v1 warehouse/basketball.duckdb --title "Warehouse 2026-07" --notes "47 seasons"
   ```
   Copy the asset's download URL. Re-run this with `data-v2`, `data-v3`...
   whenever you refresh the data, then update the secret below.
   (If you prefer not to use Releases: Cloudflare R2 has a free 10 GB tier;
   any URL that serves the file works.)

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
- **Data refresh cadence**: re-run the pipeline locally, publish a new
  Release asset, update `WAREHOUSE_URL`, reboot the app. (Automating this
  with GitHub Actions is a future session.)
