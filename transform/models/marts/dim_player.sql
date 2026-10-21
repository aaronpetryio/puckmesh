-- One row per player who has appeared on a roster, with attributes from their most
-- recent roster entry. Built from rosters (not the API's player list), which leaves out
-- the empty duplicate player records the league's database contains.
with roster as (
    select roster.*, seasons.start_date
    from {{ ref('stg_pwhl__roster_players') }} as roster
    inner join {{ ref('stg_pwhl__seasons') }} as seasons using (season_id)
),

latest as (
    select *
    from roster
    -- A player traded mid-season has two rows in that season; team_id breaks the tie
    -- only so the pick is deterministic (attributes are the same person either way).
    qualify row_number() over (partition by player_id order by start_date desc, team_id) = 1
),

career as (
    select
        player_id,
        min_by(season_id, start_date)   as first_season_id,
        max_by(season_id, start_date)   as last_season_id,
        count(distinct season_id)       as seasons_on_roster,
        count(distinct team_id)         as teams_played_for
    from roster
    group by player_id
)

select
    latest.league_id,
    latest.player_id,
    latest.first_name,
    latest.last_name,
    latest.full_name,
    latest.position,
    latest.position_group,
    latest.shoots,
    latest.birthdate,
    latest.birth_city,
    latest.birth_region,
    latest.birth_country,
    latest.height_inches,
    latest.headshot_url,
    career.first_season_id,
    career.last_season_id,
    career.seasons_on_roster,
    career.teams_played_for
from latest
inner join career using (player_id)
