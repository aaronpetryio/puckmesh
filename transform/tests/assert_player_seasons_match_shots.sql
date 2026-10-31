-- Per season, players' shooting totals should add up to fct_shots' scored shots at a goalie,
-- and their goaltending totals to fct_goalie_games. A gap means a player-season row was
-- dropped or duplicated, e.g. by the full outer join of shooting and goaltending.
-- Returns the seasons that don't reconcile.
with player_seasons as (
    select * from {{ ref('fct_player_seasons') }}
),

shots as (
    select
        season_id,
        is_goal,
        xg
    from {{ ref('fct_shots') }}
    where
        is_unblocked
        and not is_empty_net
        and xg is not null
        and season_type in ('regular', 'playoffs')
),

goalie_games as (
    select
        season_id,
        shots_faced,
        xg_faced
    from {{ ref('fct_goalie_games') }}
),

player_totals as (
    select
        season_id,
        sum(shots_on_goal) as shots_on_goal,
        sum(goals) as goals,
        sum(xg) as xg,
        coalesce(sum(shots_faced), 0) as shots_faced,
        coalesce(sum(xg_faced), 0) as xg_faced
    from player_seasons
    group by season_id
),

shot_totals as (
    select
        season_id,
        count(*) as shots_on_goal,
        count_if(is_goal) as goals,
        sum(xg) as xg
    from shots
    group by season_id
),

goalie_totals as (
    select
        season_id,
        sum(shots_faced) as shots_faced,
        sum(xg_faced) as xg_faced
    from goalie_games
    group by season_id
)

select
    player_totals.season_id,
    player_totals.shots_on_goal,
    shot_totals.shots_on_goal as shots_in_fct_shots,
    player_totals.shots_faced,
    goalie_totals.shots_faced as shots_faced_in_goalie_games
from player_totals
full outer join shot_totals on player_totals.season_id = shot_totals.season_id
full outer join goalie_totals on player_totals.season_id = goalie_totals.season_id
where
    player_totals.season_id is null
    or coalesce(player_totals.shots_on_goal, 0) != coalesce(shot_totals.shots_on_goal, 0)
    or coalesce(player_totals.goals, 0) != coalesce(shot_totals.goals, 0)
    or abs(coalesce(player_totals.xg, 0) - coalesce(shot_totals.xg, 0)) > 1e-6
    or player_totals.shots_faced != coalesce(goalie_totals.shots_faced, 0)
    or abs(player_totals.xg_faced - coalesce(goalie_totals.xg_faced, 0)) > 1e-6
