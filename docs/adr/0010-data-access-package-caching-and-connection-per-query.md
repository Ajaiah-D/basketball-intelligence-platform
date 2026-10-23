# 0010. The data access package, caching and connection-per-query

**Status:** Accepted

## Context

Every query the dashboard ran lived in one file, `dashboard/lib/db.py`,
about 1,040 lines covering every page. Results were cached with
`st.cache_data` keyed on the SQL text and its parameters only. On the
cloud, the hourly re-download cleared that cache, but anything else that
replaced the warehouse file (a local refresh, a test pointing at another
file) was answered from results of the old file until the ten-minute TTL
ran out. Six separate "does this table exist" probes caught
`(duckdb.Error, OSError)`, so a truncated download or a corrupt file was
treated the same as an older warehouse that simply lacked a table, and the
page showed a polite notice instead of failing. Tests pointed the module at
their own warehouse by monkeypatching its `DB_PATH` global.

## Decision

Replace `db.py` with the package `dashboard/lib/data/`:

- `core.py` holds the only connection and cache code: `q()` to run a
  read-only query, `objects_exist()`, `clear_caches()`, and
  `use_warehouse()`.
- One module per domain (`seasons`, `players`, `teams`, `games`,
  `advanced`, `finances`, `predictions`, `arcade`) holds plain SQL over
  the marts, returning the column names the pages show.

**Connection per query, on purpose.** Every query opens a fresh read-only
DuckDB connection and closes it. A long-lived connection would keep the
file open, and on Windows an open file can't be renamed over or deleted,
so it would block the refresh's swap
(`0009-atomic-writes-and-building-the-warehouse-in-a-copy.md`) and the app's own
re-download. A fresh connection costs a few milliseconds, and only on a
cache miss.

**Caches keyed on the warehouse version.** The cache key includes the
warehouse path and the file's modification time in nanoseconds. A
swapped-in or re-downloaded file has a new modification time, so nothing
cached from the old file can be served for it, even before
`clear_caches()` runs.

**One existence probe that hides nothing.** `objects_exist()` replaces the
six probes. It asks the catalog whether the named tables or views exist,
which can't raise a "does not exist" error, so it catches nothing: a
missing file counts as missing objects, and any other error (a truncated
download, a file that isn't a DuckDB database) raises. Pages use it only
for objects an older published warehouse may genuinely lack.

**Tests use `use_warehouse(path)`.** It points the package at a file for
the length of a `with` block and clears the caches on the way in and out,
so one test's cached results can't answer another's queries.

Considered and rejected: a shared connection held in `st.cache_resource`,
which is what locks the file; clearing the cache only when the app
downloads a new file, which misses every other way the file can change;
and an ORM or query builder, which would add a dependency for SQL that is
already short and read-only.

## Consequences

A replaced warehouse is never served from stale results, a broken one
fails loudly instead of hiding behind a notice, and tests are isolated
without touching module globals. Adding a query means adding a function to
the right domain module. The costs are a connection opened on every cache
miss, and cached results for an old file staying in memory until their
ten-minute TTL ends. Only `core.py` imports Streamlit, so the domain
modules could be served by another frontend with only that file changed
(`docs/frontend-migration-options.md`). The package never imports `ml/` or
`scripts/`, whose dependencies the deployed app doesn't install.
