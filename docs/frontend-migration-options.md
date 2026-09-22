# Moving off Streamlit: options, costs, and why we deferred

Written 2026-09-15. Status: **deferred, no work started.** Revisit if the
hosting budget changes or if the frontend becomes a portfolio priority.

## The question

Is the Streamlit dashboard slow because it is Python, and would rewriting it
as a conventional website fix that?

## What the measurements say

Warm queries against `warehouse/basketball.duckdb` (1,087,483 player-game rows):

| Query | Time |
| --- | --- |
| Season list | 1.9 ms |
| Player-season aggregate, one season | 2.4 ms |
| Standings | 1.8 ms |
| Full scan + average over 1.09M rows | 1.2 ms |
| Career aggregate, all seasons, 3,819 players | 6.9 ms |
| Arcade pool, every player-season | 8.4 ms |

The data layer is not the bottleneck. DuckDB is a C++ columnar engine; these
queries are faster than the network round trip that carries their results.

The latency visitors actually feel comes from four other places:

1. **Cold start, 30-60s.** Streamlit Community Cloud sleeps the container after
   roughly 12 hours idle. On wake it also downloads the 88 MB warehouse from the
   GitHub Release before first paint. This is a *hosting* problem.
2. **200-400 ms per interaction.** Streamlit reruns the entire script
   server-side over a websocket for every widget touch. `@st.cache_data` blunts
   it but cannot remove the round trip.
3. **Payload size.** Plotly figures are serialized to JSON and re-shipped on
   each rerun.
4. **No shareable URLs, no SEO.** Streamlit state lives in a websocket session
   rather than the URL.

Only 2 and 3 are fixed by a rewrite. Item 1, the largest single cost, is fixed
by paying for hosting.

## Options considered

### 0. Stay on Streamlit, fix the hosting

Deploy the existing `Dockerfile` to Render or Fly at roughly $7/month and bake
the warehouse into the image instead of downloading it at boot. Cold start
disappears; first paint drops under 2 seconds.

Effort: an afternoon. Delivers most of the felt speed improvement and no
frontend portfolio signal.

### 1. FastAPI + Next.js / TypeScript

`dashboard/lib/db.py` is already a clean query layer: 20 functions, SQL held in
module constants, DataFrames out. Those convert to JSON endpoints nearly
mechanically. Frontend in React with ECharts or visx. Deploy Vercel for the
frontend, Render for the API.

Effort: 60-80 hours solo for feature parity. The API half is
straightforward. The expensive half is re-implementing the 13 Plotly builders in
`dashboard/lib/viz.py`; the shot chart with its hand-drawn court shapes and the
play-by-play score worm are the fiddly ones.

Phasing that never leaves the app broken:

- **a.** Extract `db.py` into a framework-free `queries.py` with no `st.`
  imports, then put FastAPI over it. Streamlit keeps running off the same
  module, so nothing breaks.
- **b.** Build the Next.js shell and port the design tokens from `theme.py`.
- **c.** Migrate pages one at a time, easiest first: Teams, Overview, Players,
  Advanced, Games, Arcade. Both apps run side by side.
- **d.** Cut over and retire the Streamlit app.

Abandoning after any phase still leaves something that works.

### 2. DuckDB-WASM, no backend

Compile-to-WebAssembly DuckDB runs in the browser, reading the parquet files
over HTTP range requests. The same SQL executes client-side. Static hosting, no
cold start, instant interaction after load.

Effort: 50-70 hours plus real risk. `data/raw/` would need restructuring for
partial reads, and the initial download costs a few megabytes. The most
impressive option to an interviewer and the least proven.

### 3. Go or Rust backend

Not worth it. Roughly 100 hours to turn a 7 ms query into a 3 ms query. Only
sensible if the actual goal is learning the language, in which case this project
is a pretext rather than a requirement.

## Decision

Deferred on 2026-09-15. The driver was a comment that the site's performance was
probably poor; the measurements above show the criticism lands on hosting, not
on Python. Option 0 is the honest answer to that criticism and costs money we
are not spending right now.

If this is revisited, the decision should be made on what the work demonstrates
rather than on speed. The repository currently reads as strong data engineering.
A Next.js and FastAPI split would read as data engineering plus shipped
frontend. That is a career argument, not a performance one.
