-- One row per team, with its most recent name, code, and logo. Season-by-season names
-- live in stg_pwhl__teams; fct_games carries the name each game was played under.
with teams as (
    select teams.*, seasons.start_date
    from {{ ref('stg_pwhl__teams') }} as teams
    inner join {{ ref('stg_pwhl__seasons') }} as seasons using (season_id)
    where not teams.is_placeholder
),

latest as (
    select *
    from teams
    qualify row_number() over (partition by team_id order by start_date desc) = 1
),

span as (
    select
        team_id,
        min_by(season_id, start_date) as first_season_id,
        max_by(season_id, start_date) as last_season_id,
        count(*)                      as seasons_listed
    from teams
    group by team_id
)

select
    latest.league_id,
    latest.team_id,
    latest.team_code,
    latest.team_name,
    latest.city,
    latest.nickname,
    latest.conference_name,
    latest.logo_url,
    span.first_season_id,
    span.last_season_id,
    span.seasons_listed
from latest
inner join span using (team_id)
