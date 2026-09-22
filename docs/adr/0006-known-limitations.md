# 0006. Known limitations

**Status:** Accepted

## Context

Two limitations follow from earlier decisions in this platform and are
easy to lose track of once the system is working day to day: where the
refresh pipeline physically runs, and what the data source's terms allow.
Both are worth stating plainly rather than leaving implicit, since both
bound what can be safely promised about this system's reliability and its
future business use.

## Decision

Record both limitations explicitly as accepted, known constraints of the
current architecture:

1. **Single-desktop dependency.** The weekly refresh only runs if one
   specific Windows machine is on, connected, and has the Scheduled Task
   enabled (see `0004-local-task-scheduler-over-github-actions.md`) - there
   is no redundancy, and nothing in the repo alerts anyone if a refresh
   silently stops happening. `data/last_updated.json` and
   `logs/refresh_runs.jsonl` record outcomes, but nothing currently watches
   them. Losing that machine pauses all data freshness until it is
   restored or the pipeline is moved elsewhere.

2. **Monetization is constrained by the data source's terms, not by a
   formal license.** The data comes from stats.nba.com, an *unofficial*
   API accessed via `nba_api` (`README.md:37`) - there is no data license,
   formal or informal, only the general expectation that heavy or
   commercial use of an unofficial, throttled endpoint is not what it is
   meant for (`DEPLOYMENT.md:61`: "Terms allow hobby/portfolio use; it is
   not meant for a commercial product"). This is a real constraint on any
   future monetization plan, but it is a terms-of-use risk to manage, not
   a licensing agreement to renegotiate.

## Consequences

Writing these down makes the operational and business risk profile visible
to anyone reasoning about this system's reliability or its future, instead
of leaving both as tribal knowledge. It also commits them to a permanent
record as accepted debt rather than problems already being worked on.

For limitation 1, this would be resolved by adding staleness alerting on
`data/last_updated.json` / `logs/refresh_runs.jsonl`, or by moving the
refresh off the single desktop once a residential-IP-equivalent path
reachable from another host exists. For limitation 2, this would need to
be revisited only if the platform pursued a genuinely commercial use,
which would mean evaluating an official or licensed data provider rather
than continuing on an unofficial endpoint's implicit tolerance.
