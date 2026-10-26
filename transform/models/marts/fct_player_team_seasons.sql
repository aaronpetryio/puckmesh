with roster as (
    select * from {{ ref('stg_pwhl__roster_players') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

teams as (
    select
        team_id,
        season_id,
        team_code,
        team_name
    from {{ ref('stg_pwhl__teams') }}
)

select
    roster.league_id,
    roster.player_id,
    roster.team_id,
    roster.season_id,
    seasons.season_type,
    teams.team_code,
    teams.team_name,
    roster.jersey_number,
    roster.position,
    roster.position_group,
    roster.is_rookie,
    roster.roster_status
from roster
inner join seasons on roster.season_id = seasons.season_id
inner join teams
    on roster.team_id = teams.team_id
    and roster.season_id = teams.season_id
