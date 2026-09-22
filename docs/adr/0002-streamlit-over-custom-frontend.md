# 0002. Streamlit over a custom frontend

**Status:** Accepted

## Context

The dashboard could be built as a custom frontend (a FastAPI backend behind
a React/Next.js app, or a client-side DuckDB-WASM app) instead of Streamlit.
This is a solo project where speed to a working, polished product matters,
and a rewrite is a real cost measured in tens of hours, not an afternoon.

## Decision

Stay on Streamlit. `docs/frontend-migration-options.md` measured the actual
query layer (warm DuckDB queries run 1.2-8.4 ms) and found the felt latency
visitors experience comes from Streamlit Community Cloud's free-tier cold
start and its per-interaction rerun model, not from the Python data layer -
so rewriting the frontend would not fix the thing that is actually slow.
That document lays out the full options comparison (stay and fix hosting,
FastAPI + Next.js, DuckDB-WASM, a Go/Rust backend) and their costs; this
record only captures the conclusion. See that file for the analysis.

## Consequences

This keeps the project to one codebase and one deploy target, and lets
effort go toward data engineering rather than a parallel frontend rewrite.
It also means the dashboard keeps Streamlit's real limitations: no
shareable URLs, no SEO, and a per-interaction round trip that a rewrite
could reduce.

This decision was deferred, not closed, on 2026-09-15: it would be revisited
if the hosting budget changes (paying for an always-on host removes the
cold start, per `docs/frontend-migration-options.md`'s "Option 0") or if a
shipped custom frontend becomes a more valuable portfolio signal than
additional data engineering work.
