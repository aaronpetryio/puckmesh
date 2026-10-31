with shots as (
    select * from {{ ref('int_shots_enriched') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

xg_predictions as (
    select
        game_id,
        event_index,
        xg,
        xg_raw
    from {{ ref('stg_ml__xg_predictions') }}
)

select
    shots.league_id,
    shots.game_id,
    shots.event_index,
    shots.season_id,
    seasons.season_type,
    shots.period,
    shots.period_seconds,
    shots.game_seconds,

    shots.shooter_player_id,
    shots.shooting_team_id,
    shots.defending_team_id,
    shots.is_home_team,
    shots.goalie_player_id,
    shots.is_empty_net,
    shots.blocker_player_id,

    shots.shot_result,
    shots.shot_result = 'goal' as is_goal,
    shots.shot_result != 'blocked' as is_unblocked,
    shots.goal_id,
    shots.shot_type,
    shots.is_quality_chance,

    shots.x_location,
    shots.y_location,
    shots.x_ft,
    shots.y_ft,
    shots.distance_ft,
    shots.angle_deg,

    shots.goals_for_before,
    shots.goals_against_before,
    shots.score_diff,
    shots.seconds_since_team_prev_shot,
    coalesce(
        shots.seconds_since_team_prev_shot <= {{ var('rebound_window_seconds') }}, false
    ) as is_rebound,

    shots.skaters_for,
    shots.skaters_against,
    shots.strength_state,
    shots.strength_group,

    xg_predictions.xg,
    xg_predictions.xg_raw
from shots
inner join seasons on shots.season_id = seasons.season_id
-- Left: blocked, empty-net and preseason shots aren't scored, and new shots in the
-- current season wait for the next scoring run.
left join xg_predictions
    on shots.game_id = xg_predictions.game_id
    and shots.event_index = xg_predictions.event_index
