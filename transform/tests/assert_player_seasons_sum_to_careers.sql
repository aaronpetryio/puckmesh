-- A player's career counts should be the sum of their season rows, per season type.
-- Shrunk values are recomputed on the totals, so only the counts are compared.
-- Returns the player-season types that don't reconcile.
with player_seasons as (
    select * from {{ ref('fct_player_seasons') }}
),

player_careers as (
    select * from {{ ref('fct_player_careers') }}
),

season_sums as (
    select
        player_id,
        season_type,
        count(*) as seasons_played,
        sum(shots_on_goal) as shots_on_goal,
        sum(goals) as goals,
        sum(xg) as xg,
        coalesce(sum(shots_faced), 0) as shots_faced,
        coalesce(sum(goals_allowed), 0) as goals_allowed,
        coalesce(sum(xg_faced), 0) as xg_faced
    from player_seasons
    group by player_id, season_type
)

select
    coalesce(season_sums.player_id, player_careers.player_id) as player_id,
    coalesce(season_sums.season_type, player_careers.season_type) as season_type,
    season_sums.goals as season_goals,
    player_careers.goals as career_goals,
    season_sums.xg_faced as season_xg_faced,
    player_careers.xg_faced as career_xg_faced
from season_sums
full outer join player_careers
    on season_sums.player_id = player_careers.player_id
    and season_sums.season_type = player_careers.season_type
where
    season_sums.player_id is null
    or player_careers.player_id is null
    or season_sums.seasons_played != player_careers.seasons_played
    or season_sums.shots_on_goal != player_careers.shots_on_goal
    or season_sums.goals != player_careers.goals
    or abs(season_sums.xg - player_careers.xg) > 1e-6
    or season_sums.shots_faced != coalesce(player_careers.shots_faced, 0)
    or season_sums.goals_allowed != coalesce(player_careers.goals_allowed, 0)
    or abs(season_sums.xg_faced - coalesce(player_careers.xg_faced, 0)) > 1e-6
