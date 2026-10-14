-- The eight teams that actually paid luxury tax for 2023-24 (Warriors,
-- Clippers, Suns, Bucks, Celtics, Nuggets, Heat, Lakers - $521.8M in total,
-- per the league's end-of-season figures as reported by Hoops Rumors, June
-- 2024) must all be over_tax in the mart. This is the one season where the
-- payroll approximation has been checked against the official outcome.
--
-- It is deliberately one-directional. The mart also puts four teams over the
-- line that did not pay (CHI, PHI, POR, NYK, each by under $2.5M): payroll
-- here is the end-of-season roster at full salaries, while the real bill
-- prorates mid-season trades, so a team that ducked under at the deadline
-- still reads as marginally over. dashboard/lib/payroll.py's METHOD_NOTE
-- says so on the page. A real taxpayer going missing would be a data bug;
-- a marginal extra is the documented approximation.
--
-- CI note: 2023-24 is not in CI's reduced fixture set, so this passes
-- vacuously there and only earns its keep against the full local warehouse.
select season, team_abbreviation, team_payroll, luxury_tax, over_tax
from {{ ref('mart_team_finances') }}
where season = '2023-24'
  and team_abbreviation in ('GSW', 'LAC', 'PHX', 'MIL', 'BOS', 'DEN', 'MIA', 'LAL')
  and (over_tax is distinct from true)
