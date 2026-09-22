-- One row per team per season: won-loss record, scoring differential, a
-- head-to-head tiebreak, and the last-five form string. This is the
-- standings logic that used to live only in dashboard/lib/db.py's
-- standings() query, moved here so it is tested and has one home.
--
-- Conference: nba_api's static team data carries no conference field, so
-- it is assigned by team abbreviation below, covering current franchises
-- plus historical/relocated codes. Ported from the EAST/WEST sets that
-- used to be hardcoded in dashboard/lib/db.py - that module still exports
-- db.conference() for callers that want the mapping in Python, but this
-- mart is now the source of truth.
--
-- Tiebreak: the app previously ordered standings by `pct desc, net desc`,
-- which breaks a win-percentage tie on point differential alone. The
-- NBA's actual first tiebreaker is head-to-head record, so this orders by
-- win_pct, then head-to-head, then net points. head_to_head is each
-- team's win rate against the other teams it shares an exact win_pct with
-- in its own conference and season - the group the NBA would actually be
-- trying to seed apart.
--
-- This is deliberately a simplification, not an implementation of the
-- official NBA tiebreaker rules. The real rulebook continues on to
-- division record, conference record, and several further steps this
-- does not model, and even the head-to-head step here skips real wrinkles
-- of the official rule (the NBA's minimum-common-games adjustment for an
-- imbalanced schedule, and its specific handling of three-or-more-way
-- ties). Point differential is not an official NBA tiebreaker at all - it
-- is carried over from the app's prior behavior as the fallback once
-- head-to-head does not separate two teams. team_abbreviation is the
-- final sort column purely to make the result deterministic on a re-run;
-- it has no standings meaning.

with team_game as (
    -- int_team_game_opponent (Task 4) doesn't carry team_name - it wasn't
    -- needed for that model's callers - so it's pulled back in here from
    -- stg_team_game_logs on the same (game_id, team_id) grain both models
    -- share, rather than added to that already-reviewed file. Joining the
    -- season's own row (not stg_teams, a current-roster-only dimension)
    -- keeps a relocated franchise's historical name correct for its
    -- historical seasons, matching what mart_team_season already does.
    select
        i.season,
        i.team_id,
        i.team_abbreviation,
        g.team_name,
        i.opp_team_id,
        i.game_date,
        i.is_win,
        i.points,
        i.opp_points
    from {{ ref('int_team_game_opponent') }} i
    join {{ ref('stg_team_game_logs') }} g
      on g.game_id = i.game_id and g.team_id = i.team_id
),

conference_lookup as (
    select distinct
        team_abbreviation,
        case
            when team_abbreviation in (
                'ATL', 'BOS', 'BKN', 'NJN', 'CHA', 'CHH', 'CHI', 'CLE', 'DET', 'IND',
                'MIA', 'MIL', 'NYK', 'ORL', 'PHI', 'TOR', 'WAS', 'WSB'
            ) then 'East'
            else 'West'
        end as conference
    from team_game
),

totals as (
    select
        season,
        team_id,
        any_value(team_abbreviation) as team_abbreviation,
        any_value(team_name)         as team_name,
        count(*)                     as games_played,
        cast(sum(case when is_win then 1 else 0 end) as int) as wins,
        cast(sum(case when is_win then 0 else 1 end) as int) as losses,
        round(avg(case when is_win then 1.0 else 0.0 end), 3) as win_pct,
        round(avg(points), 1)          as points_per_game,
        round(avg(opp_points), 1)      as opp_points_per_game,
        round(avg(points - opp_points), 1) as net_points,
        -- Same string the app built via string_agg(win_loss, ...):
        -- int_team_game_opponent only carries the boolean is_win, so the
        -- 'W'/'L' character is rebuilt from it here instead.
        substr(string_agg(
            case when is_win then 'W' else 'L' end, '' order by game_date desc
        ), 1, 5) as form
    from team_game
    group by season, team_id
),

standings as (
    select
        t.*,
        c.conference
    from totals t
    join conference_lookup c on c.team_abbreviation = t.team_abbreviation
),

-- Teams that share an exact win_pct with at least one other team in the
-- same season and conference - the only group head-to-head needs to look
-- at.
tied_groups as (
    select season, conference, win_pct, array_agg(team_id) as tied_team_ids
    from standings
    group by season, conference, win_pct
    having count(*) > 1
),

head_to_head as (
    select
        s.season,
        s.team_id,
        round(avg(case when g.is_win then 1.0 else 0.0 end), 3) as head_to_head
    from standings s
    join tied_groups tg
      on tg.season = s.season
     and tg.conference = s.conference
     and tg.win_pct = s.win_pct
    join team_game g
      on g.season = s.season
     and g.team_id = s.team_id
     and list_contains(tg.tied_team_ids, g.opp_team_id)
    group by s.season, s.team_id
)

select
    s.season,
    s.team_id,
    s.team_abbreviation,
    s.team_name,
    s.conference,
    s.games_played,
    s.wins,
    s.losses,
    s.win_pct,
    s.points_per_game,
    s.opp_points_per_game,
    s.net_points,
    -- Neutral 0.5 when a team is not tied with anyone (nothing to break)
    -- or never played the teams it is tied with (a short/uneven schedule)
    -- - either way there is no head-to-head signal, so it must not push
    -- the team up or down against net_points.
    coalesce(h.head_to_head, 0.5) as head_to_head,
    s.form
from standings s
left join head_to_head h
       on h.season = s.season and h.team_id = s.team_id
order by
    s.season,
    s.conference,
    s.win_pct desc,
    coalesce(h.head_to_head, 0.5) desc,
    s.net_points desc,
    s.team_abbreviation asc
