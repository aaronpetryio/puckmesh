-- Empty-net goals in fct_shots should match the goal events the league flags as empty-net.
-- They're joined on goal_id, so a mismatch means a goal event has no shot event, or a
-- goal_id doesn't match. Penalty-shot goals have a goal event but no shot event, so
-- they're left out.
-- Returns the games that don't reconcile.
with shots as (
    select
        game_id,
        is_goal,
        is_empty_net
    from {{ ref('fct_shots') }}
),

goals as (
    select
        game_id,
        is_empty_net,
        is_penalty_shot
    from {{ ref('stg_pwhl__goals') }}
),

shot_empty_net_goals as (
    select
        game_id,
        count_if(is_goal and is_empty_net) as empty_net_goals
    from shots
    group by game_id
),

goal_event_empty_net_goals as (
    select
        game_id,
        count_if(is_empty_net) as empty_net_goals
    from goals
    where not coalesce(is_penalty_shot, false)
    group by game_id
)

select
    goal_event_empty_net_goals.game_id,
    goal_event_empty_net_goals.empty_net_goals as goal_events_empty_net,
    coalesce(shot_empty_net_goals.empty_net_goals, 0) as shots_empty_net
from goal_event_empty_net_goals
left join shot_empty_net_goals
    on goal_event_empty_net_goals.game_id = shot_empty_net_goals.game_id
where
    goal_event_empty_net_goals.empty_net_goals
    != coalesce(shot_empty_net_goals.empty_net_goals, 0)
