with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'goalie_change'
)

select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:team_id::string as int) as team_id,
    try_cast(event:goalie_in_id::string as int) as goalie_in_player_id,
    try_cast(event:goalie_out_id::string as int) as goalie_out_player_id,

    source_fetched_at
from events
