-- Every shot at a goalie that has xG should be counted against exactly one goalie: per
-- game, goalies' shots_faced and goals_allowed add up to fct_shots' counts. Unlike
-- assert_goalie_gsax_matches_team_xg, this also catches shots that name no goalie.
-- Returns the games that don't reconcile.
with goalie_games as (
    select
        game_id,
        shots_faced,
        goals_allowed
    from {{ ref('fct_goalie_games') }}
),

shots as (
    select
        game_id,
        is_goal
    from {{ ref('fct_shots') }}
    where
        is_unblocked
        and not is_empty_net
        and xg is not null
        and season_type in ('regular', 'playoffs')
),

goalie_totals as (
    select
        game_id,
        sum(shots_faced) as shots_faced,
        sum(goals_allowed) as goals_allowed
    from goalie_games
    group by game_id
),

shot_totals as (
    select
        game_id,
        count(*) as shots,
        count_if(is_goal) as goals
    from shots
    group by game_id
)

select
    shot_totals.game_id,
    shot_totals.shots,
    goalie_totals.shots_faced,
    shot_totals.goals,
    goalie_totals.goals_allowed
from shot_totals
left join goalie_totals on shot_totals.game_id = goalie_totals.game_id
where
    shot_totals.shots != coalesce(goalie_totals.shots_faced, 0)
    or shot_totals.goals != coalesce(goalie_totals.goals_allowed, 0)
