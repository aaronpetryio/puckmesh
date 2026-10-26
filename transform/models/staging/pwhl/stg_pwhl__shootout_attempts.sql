with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'shootout'
)

select
    league_id,
    game_id,
    season_id,
    event_index,

    try_cast(event:shot_order::string as int) as attempt_number,
    try_cast(event:player_id::string as int) as shooter_player_id,
    try_cast(event:team_id::string as int) as shooting_team_id,
    event:home::int = 1 as is_home_team,
    try_cast(event:goalie_id::string as int) as goalie_player_id,
    -- Blank on some attempts: unknown, not a miss.
    try_cast(event:goal::string as int) = 1 as is_goal,
    event:winning_goal::int = 1 as is_winning_goal,

    source_fetched_at
from events
