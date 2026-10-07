# Finances page: accurate payrolls, franchise lineage, plain-English reading

Date: 2026-10-07. Follows the 2026-09-23 team payroll feature
(`docs/superpowers/specs/2026-09-23-team-payroll-cap-history-design.md`).

## Problems

1. **Payrolls are overstated.** `ingestion/team_payroll_ingest.py` sums
   Basketball-Reference's `salaries2` table, which lists everyone who played for
   a team that season. A traded player's full salary lands on every team he
   played for (some 2023-24 teams show 39 players). The data puts 10-12 teams
   over the tax per season; the real figure is usually 6-8. The tax is assessed
   on the roster a team ends the season with.
2. **The page doesn't explain itself.** "Over cap" shows on 28-30 teams every
   year, which is normal under a soft cap, but nothing says so. There's no
   context (rank, how many other teams were over) and no cause (whose contracts
   make up the bill).
3. **Franchises are split.** Only four pure code renames merge today. Nets,
   Thunder/Sonics, Grizzlies, Pelicans/Hornets and Kings show up as separate
   teams, and the selector lists abbreviations, not names.
4. **No freshness signal.** The page doesn't say when payroll was last
   scraped. Right now payroll stops at 2025-26 while the cap seed already has
   2026-27.
5. **Overview:** the "Play-by-play games" KPI card is taller than its three
   neighbours because only it has a sub-line.

## Decisions (made with the user)

- **Re-scrape per player.** Keep player-level salary rows, and count each
  salary only for the team the player finished the season with.
- **Franchise lineage follows the contracts.** A relocation is the same legal
  business moving its contracts, so payroll history follows the business. The
  NBA's later reassignment of records (Charlotte 2014, and very likely Seattle
  if it returns) is about records, not money, and is noted on the page.

## Design

### 1. Data: per-player salaries attributed to the end-of-season team

- **Ingest.** `team_season_payroll` already parses
  `[{player, salary_usd}]`. Extend the parse to keep the bbref player id
  (`data-append-csv`). Write one row per player to
  `data/raw/team_payroll_players/{season}.parquet` with these columns: `season, team_abbreviation, bbref_player_id, player,
  salary_usd, fetched_at` (UTC timestamp of the fetch). Keep the existing
  team-total parquet too, so that its tests and the backfill script stay valid.
  A one-time full re-backfill (~1,200 pages at the existing 3.5s throttle,
  about 70 minutes) goes through `scripts/backfill_team_payroll.py`. The weekly
  refresh keeps fetching the current season only.
- **Attribution (dbt).** A new `stg_team_payroll_players` model. A player whose
  `bbref_player_id` appears on more than one team in a season is resolved by
  matching his normalized name against `raw.player_game_logs` (accents,
  punctuation and Jr./II/III suffixes stripped) and taking the team of his last
  game that season. Only multi-team players need this match. Single-team rows
  pass through untouched, including players who never played (injured or
  waived), which approximates dead money. An unmatched multi-team player stays
  on every team, is flagged, and the count of unmatched players appears in the
  page's method note. The match rate gets measured during the backfill and is
  reported, not assumed.
- **Mart.** `mart_team_finances` computes `team_payroll` from attributed rows,
  keeps `player_count` (now the end-of-season count), and adds
  `payroll_fetched_at` (max `fetched_at` for that team-season). The existing
  incompleteness flags and reasons keep their current logic. Early-era source
  gaps are unchanged.
- **Known limits, stated on the page.** A player waived after playing for one
  team and then signing with another counts only for the new team, although
  the waiving team still owes the money. Basketball-Reference lists full
  annual salaries, not prorated ones.

### 2. Franchise lineage

A small module `dashboard/lib/franchises.py` replaces
`db.MERGED_FRANCHISES`. It maps `(code, season range) → franchise` and keeps
era names:

| Franchise (listed as) | Earlier eras folded in |
|---|---|
| Oklahoma City Thunder | Seattle SuperSonics (SEA, through 2007-08) |
| Memphis Grizzlies | Vancouver Grizzlies (VAN) |
| Brooklyn Nets | New Jersey Nets (NJN) |
| Sacramento Kings | Kansas City Kings (KCK) |
| New Orleans Pelicans | Charlotte Hornets (CHH 1988-89 to 2001-02), New Orleans Hornets (NOH), New Orleans/Oklahoma City Hornets (NOK) |
| Charlotte Hornets | Charlotte Bobcats (CHA 2004-05 to 2013-14) |
| Golden State / Philadelphia / San Antonio / Utah | existing legacy code renames |
| Washington Wizards | Washington Bullets (through 1996-97) |

Mapping depends on the season range, so a future expansion team reusing `SEA`
stays its own franchise. Notes rendered on the page:
- **Charlotte Hornets:** "The NBA credits the 1988-2002 Hornets records to
  Charlotte, but those contracts moved to New Orleans in 2002, so that payroll
  is shown under the Pelicans."
- **Thunder:** "The SuperSonics name and history were kept for Seattle; the
  contracts and roster moved to Oklahoma City, so 1984-2008 payroll is shown
  here."

The selector lists full current names, and the chart labels each era.

### 3. Page layout (top to bottom)

1. **Header line.** "Salary data updated {date} · through {latest payroll
   season}". If the cap seed has a later season than payroll, add "{season}
   payrolls not loaded yet".
2. **Season snapshot.** A season selector (default: latest payroll season)
   and a horizontal bar chart of all 30 teams' payrolls with the cap, tax and
   apron lines. Bars are colored by bracket. A summary line follows: "{n} teams
   over the tax, {m} over the first apron, {k} over the second."
3. **"How to read this" expander, open by default on first view.** One plain
   sentence per line:
   - Cap: soft, so being over it is normal (Bird rights, exceptions,
     minimums).
   - Tax: every dollar over is taxed, starting at $1.50 per dollar and
     climbing, with higher rates for repeat offenders.
   - First and second aprons (2023-24 on): lose trade and signing tools; the
     second apron also freezes a future first-round pick.
4. **Team view.** A selector by full name, then a generated summary sentence:
   "In 2025-26 the Boston Celtics spent $193M, 4th of 30 teams and $22M over
   the luxury tax line, one of 8 tax teams. Their three biggest contracts
   (A, B, C) made up 61% of payroll." The KPI cards stay (payroll, rank,
   status). A **biggest contracts** list shows the top 5 salaries with share of
   payroll, plus a muted "traded away mid-season, not counted" list when it
   isn't empty.
5. **History chart.** The existing shaded-zones chart, with era bands and
   labels for franchise eras. The full table stays in an expander.
6. **Method note.** Source, the end-of-season attribution rule, its known
   limits, and the unmatched-player count.

### 4. Overview KPI cards

All four KPI cards in a row render at equal height. The play-by-play note stays
inside its card. Done in CSS on `.bip-kpi` rows (stretch to the tallest card),
so every KPI row on the site benefits. It gets checked visually with a
Playwright screenshot.

## Testing

- **Ingest:** parsing keeps the bbref id. The per-player parquet schema is
  checked against fixture HTML.
- **dbt:** the attribution test checks that a multi-team player is counted on
  exactly one team, against a fixture with a known mid-season trade. The
  existing mart tests continue to pass. The CI fixture gets a per-player
  parquet.
- **franchises.py:**
  - Season-aware mapping, including that a hypothetical post-2008 `SEA` does
    not map to OKC.
  - Every code in the mart maps to exactly one franchise.
  - CHH maps to NOP.
  - The tests asserting SEA/OKC stay separate (`tests/test_db_metrics.py`) get
    rewritten for the new rule.
- **Page:** AppTest renders with and without the per-player table (an older
  published warehouse), and checks that the summary sentence and updated-date
  line render.
- **Sanity check after the backfill:** the per-season tax-team counts land in
  the realistic 2-12 range, and spot checks of 2023-24 and 2024-25 against
  public end-of-season payroll reporting fall within a few million.

## Out of scope

Estimated tax bills in dollars (attribution is approximate, so a precise
bill would overclaim), contract lengths or future years, and per-player cap
holds.
