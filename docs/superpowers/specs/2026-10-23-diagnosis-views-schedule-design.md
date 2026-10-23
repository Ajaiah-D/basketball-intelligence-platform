# Diagnosis views, a Schedule page and a simpler Predictions page

Date: 2026-10-23. Inspiration: hoopologyviz.com (its season calendar, team
dashboard, scatter plots and leaders).

## Goal

Help a fan who knows basketball (the owner, and anyone he shares the site
with) reason about teams in three steps:

1. **What is this team good and bad at?**
2. **Which players cause it?**
3. **How does that compare to the rest of the league?**

The pages should stay clean: every view answers one question. Film and
context still matter. This is a starting point for asking better questions,
not a verdict.

Decisions made with the owner:

- **Players page:** a scatter, a game log with an any-stat trend, and a
  head-to-head compare.
- **Teams page:** an any-two-stats scatter.
- **Schedule:** its own page.
- **Monthly splits** were dropped: they show *when* a team was good, not
  *what* it is good at. Step 1 is covered by the strengths and weaknesses
  profile instead, and step 2 by "who drives it".
- **Predictions page:** made simpler. The owner found it clunky, too big for
  what it says, and its two-colour bars ugly.

## Teams page (the Team tab)

### 1. Strengths and weaknesses (replaces the Four Factors section)

One horizontal percentile chart of about 14 stats, in three groups. Each bar
shows where the team ranks in that season's league (1-30), coloured from
weak to strong. The value and the rank are printed on the bar.
"Better" is always to the right, so a low turnover rate counts as a
strength.

| Group | Stats |
|---|---|
| Offense | Offensive rating, effective FG%, 3P%, 3-point attempt rate, turnover rate, offensive rebound %, free throw rate, assist rate |
| Defense | Defensive rating, opponent eFG%, opponent 3P%, opponent turnover rate (forced), defensive rebound %, opponent free throw rate |
| Style | Pace (shown as context, not judged good or bad) |

- A one-line summary sits above the chart: "Best at: … · Worst at: …", from
  the three strongest and three weakest ranks.
- Every stat name has the site's hover explanation.
- For early seasons without the inputs, the bars simply don't show, as the
  current Four Factors does.

### 2. Who drives it (new)

A selector for the area to look at:

| Area | Team stat | Player measures |
|---|---|---|
| Scoring efficiency | eFG% | TS% and usage |
| 3-point shooting | 3P% | 3PA per game (share of the team's) and 3P% |
| Ball security | Turnover rate | Turnover rate and usage |
| Offensive rebounding | Offensive rebound % | Offensive rebound rate |
| Defensive rebounding | Defensive rebound % | Defensive rebound rate |
| Getting to the line | Free throw rate | Free throw rate |
| Playmaking | Assist rate | Assist rate |
| Disruption | Opponent turnover rate | Steal rate and block rate |

It shows:

- the team's rank in that area;
- a compact chart of the rotation (players with 10+ games for the team), each
  player's measure next to the league's median line for that measure, sized
  by minutes;
- a one-line read, generated from the numbers, e.g. "Most of BOS's threes
  come from Tatum and Brown, both above league median at 37%+".

Clicking a player opens him on the Players page, which is step 2 to step 3.

Box scores show offense far better than defense. The caption says so plainly
for the defensive areas.

### 3. Team scatter (replaces the fixed offense-vs-defense chart)

- Two stat pickers over the profile stats.
- Default: offensive rating vs defensive rating, with the quadrant labels
  kept.
- All 30 teams in their colours; the selected team is highlighted; dashed
  lines at the league average.

## Players page: three tabs

### Stats (today's table and player detail, plus)

- **Game log:** one row per game: date, opponent, result, minutes, points,
  rebounds, assists, 3PM, TS%, plus-minus. Each stat is tinted green or red
  against his season average.
- **Trend chart:** a stat picker (points, rebounds, assists, 3PM, TS%,
  plus-minus) with a 5-game rolling line. It replaces today's points-only
  trend.

### Scatter

- **Controls:** season, two stat pickers (defaults: points per game vs true
  shooting %), a minimum-games filter (default 25, or the season's
  qualification threshold early in a season) and a team filter.
- **Chart:** every qualified player is a team-coloured dot, with dashed lines
  at the league average. About 12 standout players are labelled: the
  farthest from the average point, plus the selected team's players.
- **Hover:** shows the player's line.
- No headshots: hundreds of embedded images would make the page slow.

### Compare

- Two player-season searches (any season, any era, the same accent-blind
  search as the Players table).
- Side-by-side stat bars.
- A percentile radar of about 8 measures: scoring, efficiency, rebounding,
  playmaking, ball security, steals, blocks, 3-point volume. Each player is
  ranked against his own season's qualified players, so different eras
  compare fairly.

## Schedule page (new, in the sidebar)

- **Month calendar:** previous/next arrows, the current month by default. Each
  day is a clickable cell showing its game count. It's a grid of Streamlit
  buttons, because Streamlit can't catch clicks on HTML.
- **Day view:** that day's games as compact rows, one line each.
  - Finished games: the final score and the game's top scorer, plus an
    "Open game" button that goes to the Games page with that game selected.
  - Upcoming games: tip-off time (ET) and the model's pick with its win
    probability.
- **Team filter:** the calendar cells show that team's opponent ("vs BOS" /
  "@ BOS") instead of counts, and a list of the team's whole season appears
  (date, opponent, result or tip-off, running record).
- **Data:** the published schedule (`stg_schedule`) joined to results
  (`fct_team_game`) and predictions, all already in the warehouse.

## Predictions page: simpler

- **Upcoming games:** a compact list grouped by day, one row per game:
  `7:00 PM  NYK @ BOS   BOS 65%  by 5`.
  - The favourite's probability is shown once, with a thin single-colour
    confidence bar in the favourite's colour, from 50% to 100%.
  - Games under 55% are marked "toss-up".
  - Each value appears once, with no two-colour bars.
- **Track record:** one row of three KPIs: accuracy, Brier score, margin
  error.
- **Detail:** the calibration chart and "How these are made" move into one
  collapsed expander.
- **Recent results:** a compact table (matchup, pick, probability, final,
  ✓/✗) with the 10 most recent games.
- **Navigation:** the page links to the Schedule page for anything beyond the
  next 7 days.

## Data (dbt first, then pages: expand then contract)

New marts, additive. They are published by a refresh before the pages that
read them merge.

- **`mart_team_profile`** (grain: season × team):
  - every profile stat;
  - its league rank and percentile within the season, with direction-aware
    ranking (lower turnover rate ranks better);
  - the stats not already in `mart_team_season`: 3P%, 3-point attempt rate,
    opponent 3P%, opponent 3-point attempt rate.
- **`mart_player_percentiles`** (grain: season × player): percentile within
  the season among qualified players (the dashboard's qualification rule,
  moved into SQL) for each radar and "who drives it" measure.
- **"Who drives it":** reads `mart_player_team_season` (per-team stints) for
  minutes and volume, and `mart_player_season` for rates.
  - A traded player's rates cover his whole season, not just his time on
    this team; the caption says so.
- **Schedule:** reads only existing published objects.

## Testing

- **dbt:**
  - grain (`unique` and `not_null`);
  - ranks in 1..30 per season;
  - percentiles in 0..100;
  - a direction test: turnover-rate rank 1 is the lowest rate.
- **Data layer:** tests on fixtures and the real warehouse through
  `use_warehouse`.
- **Pages:**
  - AppTest renders every new tab and page;
  - the Schedule "Open game" round-trip;
  - the team filter;
  - an empty day;
  - the offseason.
- **Visual:** a Playwright screenshot pass on every page that changes.
- **Gates:** the existing CI gates (ruff, mypy, import boundaries, skip
  guard).

## Out of scope

Shot zones and play types (the data doesn't have them beyond accumulated
play-by-play), on/off splits, headshots in the scatter, monthly splits,
exporting charts.
