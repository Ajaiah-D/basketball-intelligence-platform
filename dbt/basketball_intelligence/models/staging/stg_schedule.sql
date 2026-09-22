-- One row per scheduled game, including games not yet played.
-- gameStatus is 1 for scheduled, 2 for in progress, 3 for final.
--
-- gameDate comes back from ScheduleLeagueV2 as "MM/DD/YYYY HH:MM:SS", not
-- ISO 8601, so a plain cast to date fails - parse it explicitly instead.
--
-- gameStatus alone does not separate preseason from the real regular
-- season - filtering only on gameStatus = 1 for 2026-27 returns 1,274
-- games from 2026-10-03, when the real season (confirmed against
-- stg_team_game_logs, where every known completed regular-season game_id
-- starts '002') opens 2026-10-20 with 1,206 games. The first three
-- characters of game_id encode game type: '001' preseason, '002' regular
-- season (the only prefix ever seen in completed data), '004' playoffs.
-- Exposed here so every consumer (predictions, Task 9) filters the same
-- way instead of re-deriving it.

select
    cast(seasonYear as varchar)                            as season,
    cast(gameId as varchar)                                as game_id,
    cast(strptime(gameDate, '%m/%d/%Y %H:%M:%S') as date)  as game_date,
    cast(gameDateTimeUTC as timestamp)                     as tipoff_utc,
    cast(homeTeam_teamId as bigint)                        as home_team_id,
    cast(homeTeam_teamTricode as varchar)                  as home_team_abbreviation,
    cast(awayTeam_teamId as bigint)                        as away_team_id,
    cast(awayTeam_teamTricode as varchar)                  as away_team_abbreviation,
    coalesce(cast(isNeutral as boolean), false)            as is_neutral_site,
    cast(gameStatus as integer)                            as game_status,
    substr(cast(gameId as varchar), 1, 3) = '002'          as is_regular_season
from {{ source('raw', 'schedule') }}
