# Contracts & Salary Cap: Data Source Research

Research pass conducted 2026-09-22 to scope a possible future "Contracts & Salary Cap" module
(team payrolls, individual contract terms, league cap/tax thresholds) alongside the existing
performance-stats platform. **No implementation decisions made here — findings only.**

`nba_api` (this project's existing ingestion library) does not cover contracts/salaries at all,
so this is a genuinely new data-sourcing problem, not an extension of the existing pipeline.

## 1. Source comparison

| Source | Coverage depth | History depth | Access method | ToS / scraping risk | Cost | Staleness risk |
|---|---|---|---|---|---|---|
| **Spotrac** | Deepest structural detail: cap hits, options, guarantees, bonuses, trade kickers, dead money, apron math | Full current-era detail; older years thinner | No documented public API; HTML only, CloudFront-fronted | 🔴 Red — ToS explicitly bars systematic extraction and redistribution without written permission; robots.txt explicitly blocks `anthropic-ai`/`Claude`/etc. | Free to browse; paid API product exists, pricing not confirmed | Live/frequent — best freshness of any source |
| **Basketball-Reference / Sports-Reference** | Player contracts, team payrolls, payroll notes; official NBA stats partner | Salary tables back to the 1980s, explicitly filled/extrapolated with minimums for missing years | No public API; HTML only, but a published bot policy exists (20 req/min general, 10 for Stathead/FBref) | 🟡 Yellow — ToS prohibits building tools/sites from scraped data or AI training use without permission, but the published rate-limit policy implies polite scraping is tolerated; redistribution is the risky part | Free; Stathead subscription from ~$9/mo | Updated regularly in-season/offseason |
| **HoopsHype** | Player/team salary & cap-hit pages, agent listings | Historical years present but reportedly pruned in places | No API; HTML only | 🟡 Yellow — no explicit scraping ToS found, but robots.txt disallows `anthropic-ai`/`Claude`/`GPTBot`/`Google-Extended` | Free | Reportedly gappy/manually curated |
| **RealGM** | CBA salary scale, cap history table | Multi-decade cap history | No API; HTML only | 🔴 Red — Terms of Use state content is for entertainment purposes only and require "human being, unaided by a computer" access — an explicit categorical scraping ban | Free | Unclear |
| **ESPN** | Player salary lists by year | ~1999-2000 forward | No documented salary API; HTML only | 🟡 Yellow — general anti-scraping ToS, doesn't single out salary pages | Free | Annual-ish; no options/bonus breakdown |
| **NBA.com press releases** | League-wide cap/tax/apron/floor thresholds only — no player or team payroll data | Figures exist per-season back to 1984-85 (via secondary corroboration) | Official press releases, trivially fetchable | 🟢 Green — league publishing its own numbers | Free | Set annually (~June/July) |
| **NBPA (LM-2 filings)** | Executive compensation only, not player contracts | N/A | Public federal filings | 🟢 Green, but not useful for this purpose | Free | N/A |
| **Patricia Bender's DB** (eskimo.com/~pbender) | Historical salaries, results, standings, draft, awards | 1993-94 through 2017-18, then frozen (owner stopped updating Oct 2018) | No API; static personal HTML | 🟡 Yellow — no explicit license/ToS, default copyright applies, redistribution legality ambiguous | Free | Frozen — one-time backfill value only |
| **USA Today Sports Salaries DB** | — | — | Could not locate a live 2026 instance | Unknown | Unknown | Likely defunct |
| **Kaggle datasets** | Varies; mostly single/few-season CSVs sourced from BBRef/ESPN by third parties | 1-6 seasons typically | CSV download | 🟢 Kaggle hosting itself; 🟡 underlying source ToS still applies | Free | Static snapshots — backfill only |
| **SalarySwish / Capsheets** | Cap tracker, trade machine, comparables | Current-era focus | No API found; HTML | Unknown — no ToS text found | Unknown | Unknown |

**Anti-bot signal found:** automated `WebFetch` got 403s from Spotrac, RealGM's robots.txt, and
Sports-Reference's data-use page, while a plain `curl` with a generic browser User-Agent got a
clean 200 from Spotrac. Spotrac's and HoopsHype's own robots.txt explicitly `Disallow: /` for
named AI-crawler user agents. A conventional scraper would likely get through technically but
would be doing so against the written ToS on Spotrac and RealGM specifically, and against an
explicit anti-AI-agent robots directive on Spotrac/HoopsHype.

## 2. Domain complexity a data model needs to represent

Each of these breaks a naive "one salary number per player-season" model in a specific way:

- **Player option / team option / early termination option (ETO).** A contract's final year(s)
  may not happen at the listed amount — the player, team, or (for ETOs, 5+ year deals only,
  not exercisable before year 4) either side can end it early. A flat per-year dollar model
  overstates future payroll commitments whenever an option year exists; needs an explicit
  per-contract-year status field (guaranteed / player-option / team-option / ETO), not just a
  dollar figure.
- **Guaranteed vs. non-guaranteed money.** Independent of option type — a year's salary can be
  partially/fully non-guaranteed, meaning the team can waive the player and owe nothing or only
  a portion. A separate axis from option type; needs its own field.
- **Likely vs. unlikely bonuses.** A bonus counts as "likely" (and hits the current cap) if its
  trigger condition was met the *preceding* season, regardless of how achievable it is this
  year; "unlikely" bonuses don't count against the cap now even if later earned, though they do
  factor into "Apron Team Salary." True cap hit = base salary +/- a bonus adjustment whose sign
  depends on last year's outcome, not a single "total compensation" number.
- **Trade kickers.** Up to 15% of remaining contract value, capped so the player can't exceed
  max salary, paid by the trading team, spread over remaining guaranteed years, waivable by the
  player. Not resolvable at signing time — only becomes concrete (or void) at the moment of an
  actual future trade, so it's a rule to evaluate against a transaction, not a static field.
- **Dead cap money / stretch provision.** A waived player's guaranteed salary typically still
  counts against the team's cap ("dead money") unless the team stretches it (spread over up to
  2x remaining years + 1). This money isn't tied to any player currently on the roster or even
  in the league — needs its own ledger entry keyed to team + season, not derived from an
  active-roster join.
- **Two-way and Exhibit 10 contracts.** Real, dollar-denominated contracts (max 3 two-way, max 6
  flagged Exhibit 10 per team) that generally do **not** count against the cap while active. Must
  exist in a contracts table for completeness but must be excluded from payroll/cap-total
  queries or those will overstate real commitments.
- **Cap holds.** A placeholder cap figure a team carries for its own pending free agents (no
  active contract exists yet), sized by Bird-rights rules or draft-pick multipliers. Needs its
  own row-type, distinct from an actual contract, that disappears once the player signs or is
  renounced.
- **Salary cap vs. luxury tax vs. first apron vs. second apron.** Four separate annually-set
  thresholds (2026-27: cap $164.961M / tax $200.428M / first apron $209.015M / second apron
  $221.686M), each unlocking or removing different roster tools. "Over the cap" alone is normal
  (soft cap); the apron lines (2023 CBA) remove exceptions and impose hard trade restrictions.
  "Team Salary" for tax purposes and "Apron Team Salary" are computed differently (the latter
  adds back unlikely bonuses and minimum-salary adjustments) — one payroll number can't answer
  both "over the tax?" and "over the apron?"
- **No salary cap existed before 1984-85.** Team spending was unconstrained before the 1983 CBA
  (first cap: $3.6M/team, effective 1984-85). Hard-bounds any cap-relative metric to 1984-85
  forward (~42 seasons as of 2026-27); raw player salaries can in principle go back further but
  both major sources (Basketball-Reference, Bender) acknowledge partial reconstruction/
  extrapolation for those years.

## 3. Feasibility read

**Realistic history depth:**
- Cap/tax/apron thresholds: essentially complete, low-risk, back to 1984-85 (official press
  releases, corroborated on Basketball-Reference).
- Player/team salary dollars: obtainable back to the mid-1980s with acknowledged quality
  degradation in early years (documented extrapolation/minimum-filling on Basketball-Reference;
  Bender's database — a major original source for that era — has known gaps and has been frozen
  since October 2018).
- Contract structure detail (options, bonuses, kickers, guarantees): realistically only reliable
  for the more recent era (~2010s forward) where Spotrac/Basketball-Reference actively track it.

**Realistic freshness achievable:** weekly is consistent with actual source update cadence —
none of these sites update faster than that outside trade-deadline/free-agency windows, and
cap/tax/apron figures change once a year. Fits this project's existing weekly-local-refresh
constraint without meaningfully lagging reality.

**Single biggest risk — legal, not technical:** this project already publishes its warehouse as
a public GitHub Release asset and runs a public dashboard. Spotrac and RealGM's ToS go beyond
"no bots" to explicitly prohibit *redistribution* of their data, which is a materially different
problem than the stats.nba.com precedent — that one is purely technical (cloud IP blocking,
solved by running locally); this one means even successfully-scraped data becomes contractually
risky to *publish*, regardless of where the scraper runs. Basketball-Reference sits in a middle
zone: a published rate-limit policy suggests tolerated scraping, but the ToS text still separately
discourages building tools from the scraped data. The anti-AI-crawler robots.txt entries on
Spotrac/HoopsHype are a second, compounding signal on top of the legal one.

## 4. Prior art found

- **[cubeerea/NBA-contract-analytics](https://github.com/cubeerea/NBA-contract-analytics)** —
  MIT, actively pushed as of 2026-09-21. Nightly GitHub Actions ETL pulling salary from
  Basketball-Reference `/contracts/` (~30 requests, under BBRef's 20 req/min limit), enriched
  with Spotrac contract structure treated as optional/degradable, not a hard dependency — a
  direct mitigation for the ToS risk above. Independently confirms stats.nba.com's IP/TLS
  fingerprint blocking (cites `nba_api` issue #633) and that `nba_api.stats.static.players` is
  the one bundled-local, zero-HTTP piece safe under that block. Also documents deriving CBA
  minimums as a percentage of the live cap rather than a hardcoded dollar literal, since the
  literal silently breaks every following season.
- **[atlhawksfanatic/bender-salaries](https://github.com/atlhawksfanatic/bender-salaries)** —
  GPLv3, dormant since 2022-04-13. Scrapes/structures Patricia Bender's database — one-time
  historical-backfill value for the 1993-2018 window, not an ongoing feed.
- **[atlhawksfanatic/NBA-CBA](https://atlhawksfanatic.github.io/NBA-CBA/)** — structured
  rendering of the actual 2023 CBA text (option clauses, likely/unlikely bonus definitions) —
  strong primary-source reference for the domain model, not a data feed.
- **hoopR / SportsDataverse** (https://hoopr.sportsdataverse.org/) — MIT, actively maintained R
  package family; includes `spotrac_team_cap()` with no API key — evidence Spotrac's HTML is
  technically scrapable, though this doesn't resolve the ToS redistribution risk.
- **Kaggle datasets** — static single/few-season CSV snapshots, backfill/cross-check value only.
- **JovaniPink/awesome-nba-data** — MIT-licensed curated NBA data-source catalog with **no
  entry at all** for any salary/contract/cap source — confirms this is a genuine, unfilled gap
  in the open-source NBA-data ecosystem.

## 5. Open questions (not research-answerable — decisions for later)

- Is a paid tier (Spotrac API, Stathead ~$9/mo) worth it to sidestep the ToS/anti-bot problem —
  a budget call, not a research finding.
- Risk tolerance for publishing data derived from Spotrac/RealGM despite their redistribution
  ToS — a legal-risk-appetite judgment call, common in hobbyist sports analytics but not
  something research can resolve.
- Whether pre-1984-85 "salary" data (no cap existed, numbers partly reconstructed/estimated) is
  worth including at all, or whether the module's floor should simply be 1984-85.
- Whether HoopsHype's apparent pruning of older seasons is a hard cutoff or recoverable via the
  Wayback Machine — not checked this pass.
- Whether Spotrac's paid developer API actually documents NBA-specific endpoints — its page
  403'd automated fetches in this research session; would need a direct signup/trial to confirm.

---

**Explicitly out of scope for this document:** schema design, dbt model names, ingestion script
architecture. This is findings only — the next step, if pursued, is a design/brainstorm pass
once these findings are reviewed.
