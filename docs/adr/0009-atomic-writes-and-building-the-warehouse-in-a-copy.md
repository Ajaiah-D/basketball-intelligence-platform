# 0009. Atomic writes and building the warehouse in a copy

**Status:** Accepted

## Context

The weekly refresh (`0004-local-task-scheduler-over-github-actions.md`)
wrote everything in place. Each step rewrote `warehouse/basketball.duckdb`
directly, so a run that failed halfway through dbt left a half-built
warehouse on disk for the next run, and for any local dashboard, to read.
Parquet files were written with a plain `to_parquet()`: a run killed
mid-write (Ctrl+C, a reboot, a full disk) left a file without its footer,
and because "done" only meant "the file exists", that broken season was
skipped by every later run. `version.txt`, the marker the live app watches
to know when to re-download, was written before the upload and uploaded
alongside the warehouse, so it could announce data that hadn't arrived.
Predictions lived only in a warehouse table, so losing the file lost the
track record, and a run that predicted but then failed still kept its rows.
The data sat inside OneDrive, whose sync can lock or half-upload a large
file while it's being written.

## Decision

Nothing the pipeline writes is ever half-written, and a run either
publishes everything or changes nothing.

1. **Atomic file writes.** `core/io.py` writes to a temp file and swaps it
   in with `os.replace`, and a season counts as done only if its parquet
   footer reads. Replacing a season file with an empty one, or one under
   80% of its rows, is refused. Only transient errors (timeouts, connection
   errors, 5xx, 429 with its `Retry-After`) are retried.
2. **Build in a copy, then swap.** The refresh copies the warehouse to
   `warehouse/next/basketball.duckdb`, and every step reads and writes that
   copy (`BIP_WAREHOUSE` points them at it). Only when every required step
   has passed is the copy moved onto `warehouse/basketball.duckdb` with
   `os.replace`; on any failure the copy is deleted. The swap retries for
   about 20 seconds, because Windows refuses to rename over a file that
   another process (an indexer, antivirus, a local dashboard) briefly has
   open.
3. **The copy keeps the warehouse's file name.** dbt-duckdb names the
   catalog after the file stem and writes it into every view it creates
   (`from basketball.raw.players`). A copy named `basketball_next.duckdb`
   would hold views pointing at a `basketball_next` catalog, which stop
   resolving the moment the file is renamed onto `basketball.duckdb`. So
   the copy sits in its own folder under the same name, which also keeps
   it on the same filesystem, so the swap is a single rename.
4. **Publish in order.** The warehouse is uploaded first; `version.txt` is
   written only after that upload succeeds, and uploaded second. If the
   marker's upload fails, the local file is put back and the run fails.
5. **Predictions in a committed CSV.** `data/predictions/history.csv` is
   the source of truth for every published prediction, and the
   warehouse's predictions table is rebuilt from it on each load. A
   publishing run first snapshots the CSV (`history.csv.pre-run`). The
   rollback is keyed on whether the warehouse was uploaded, not on whether
   the run succeeded: once the asset is up, its predictions are public and
   stay, even if the `version.txt` upload then fails. Any other ending puts
   the CSV back. A run killed outright never reaches that cleanup, so every
   run starts by restoring from a snapshot it finds left over.
6. **Guard rails.** A lock (`logs/refresh.lock`) stops overlapping runs,
   each step has a timeout and is killed with its whole process tree,
   every step's output goes to `logs/runs/<run time>/`, and
   `--no-publish` runs every step against the copy and then deletes it
   (with `BIP_DRY_RUN=1`, so it adds no predictions either).
7. **Data outside OneDrive.** `BIP_DATA_HOME` moves `raw/` and
   `warehouse/` to any folder; the refresh machine keeps them outside the
   sync folder.

Considered and rejected: one DuckDB transaction around the build, which
can't work because dbt and the Python steps are separate processes running
many statements each; backing the warehouse up before the run and
restoring it on failure, which leaves the live file broken while the run
is going and depends on the restore itself not failing; and keeping
predictions only in the warehouse, which ties the track record to one
regenerated binary file with no history.

## Consequences

A failed run leaves the warehouse, the release and the predictions
history exactly as the last good run left them, and a dry run can be done
at any time without touching anything published. The costs: the refresh
needs disk for a second copy of the warehouse (about 90 MB); a local
dashboard holding the warehouse open blocks the swap, and the run fails
until it is closed; and if the warehouse uploads but `version.txt`
doesn't, running apps stay on the old data until the next good run. One
small window remains: a run killed in the instant between the upload
finishing and the snapshot being deleted would have its published
predictions rolled back by the next run.
