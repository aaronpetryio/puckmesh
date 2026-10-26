with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'hit'
)

-- One row per hit. Not recorded for every game.
select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:player_id::string as int) as hitter_player_id,
    try_cast(event:team_id::string as int) as hitting_team_id,
    event:home::int = 1 as is_home_team,
    try_cast(event:hit_type::string as int) as hit_type_id,
    try_cast(event:x_location::string as int) as x_location,
    try_cast(event:y_location::string as int) as y_location,

    source_fetched_at
from events
