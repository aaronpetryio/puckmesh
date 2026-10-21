-- One row per player per team per season they were rostered: the career-history table.
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
from {{ ref('stg_pwhl__roster_players') }} as roster
inner join {{ ref('stg_pwhl__seasons') }} as seasons using (season_id)
inner join {{ ref('stg_pwhl__teams') }} as teams using (team_id, season_id)
