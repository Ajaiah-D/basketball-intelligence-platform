# 0001. DuckDB over Postgres for the warehouse

**Status:** Accepted

## Context

The platform needed a warehouse for 47 seasons of NBA history queried in
analytical (OLAP) patterns: season aggregates, career rollups, full-table
scans. This is a solo project with one write path (the weekly refresh) and
one read path (the dashboard) - there is no requirement for concurrent
writers or a network-addressable database server, and running a hosted
Postgres instance would mean provisioning, paying for, and keeping alive a
server that sits idle between refreshes.

## Decision

Use DuckDB: a single-file, zero-server, embedded OLAP database. The entire
warehouse lives in one file, `warehouse/basketball.duckdb` (~92 MB as of
this writing, covering all 47 backfilled seasons), which is distributed as
a GitHub Release asset rather than run as a hosted service (see
`0003-github-release-asset-for-data.md`).

## Consequences

This eliminates server provisioning, hosting cost, and uptime management
for the database entirely - the "database" is just a file the app opens.
Analytical queries over the full history run in single-digit milliseconds
because DuckDB is a columnar engine built for exactly this access pattern.

The trade-off is DuckDB's file has no concurrent writers and no network
access from outside the process that opened it: only one process can hold
the file open for writing at a time, and nothing can query it remotely
without shipping the whole file first. Both are fine today because the
refresh and the dashboard never write at the same time and the app always
opens its own local copy. This would need to be revisited if the platform
ever needed multiple simultaneous writers, or a backend that serves several
independent app instances against one live, continuously-updated database
rather than a periodically republished file.
