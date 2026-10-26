with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'penaltyshot'
)

select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:id::string as int) as penalty_shot_id,
    try_cast(event:player_id::string as int) as shooter_player_id,
    try_cast(event:team_id::string as int) as shooting_team_id,
    event:home::int = 1 as is_home_team,
    try_cast(event:goalie_id::string as int) as goalie_player_id,
    event:result::string as result,
    try_cast(event:game_goal_id::string as int) as goal_id,

    source_fetched_at
from events
