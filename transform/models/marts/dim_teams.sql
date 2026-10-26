-- Season-by-season names live in stg_pwhl__teams; fct_games carries the name each game
-- was played under.
with stg_teams as (
    select * from {{ ref('stg_pwhl__teams') }}
),

seasons as (
    select
        season_id,
        start_date
    from {{ ref('stg_pwhl__seasons') }}
),

teams as (
    select
        stg_teams.*,
        seasons.start_date
    from stg_teams
    inner join seasons on stg_teams.season_id = seasons.season_id
    where not stg_teams.is_placeholder
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
        count(*) as seasons_listed
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
inner join span on latest.team_id = span.team_id
