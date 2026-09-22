-- One row per scheduled game, including games not yet played.
-- gameStatus is 1 for scheduled, 2 for in progress, 3 for final.
--
-- gameDate comes back from ScheduleLeagueV2 as "MM/DD/YYYY HH:MM:SS", not
-- ISO 8601, so a plain cast to date fails - parse it explicitly instead.

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
    cast(gameStatus as integer)                            as game_status
from {{ source('raw', 'schedule') }}
