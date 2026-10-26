with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'faceoff'
)

-- One row per faceoff.
select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:home_player_id::string as int) as home_player_id,
    try_cast(event:visitor_player_id::string as int) as away_player_id,
    try_cast(event:win_team_id::string as int) as winning_team_id,
    event:home_win::int = 1 as home_won,

    try_cast(event:location_id::string as int) as faceoff_location_id,
    try_cast(event:x_location::string as int) as x_location,
    try_cast(event:y_location::string as int) as y_location,

    source_fetched_at
from events
