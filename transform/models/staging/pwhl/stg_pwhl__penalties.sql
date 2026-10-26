with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'penalty'
)

select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:id::string as int) as penalty_id,
    try_cast(event:team_id::string as int) as penalized_team_id,
    event:home::int = 1 as is_home_team,
    -- Null for bench minors; served_by is who sat in the box.
    try_cast(event:player_id::string as int) as penalized_player_id,
    try_cast(event:player_served::string as int) as served_by_player_id,
    event:bench::int = 1 as is_bench_penalty,

    event:lang_penalty_description::string as infraction,
    event:penalty_class::string as penalty_class,
    try_cast(event:minutes::string as decimal(4, 2)) as penalty_minutes,
    event:pp::int = 1 as is_power_play_penalty,
    event:penalty_shot::int = 1 as is_penalty_shot,

    source_fetched_at
from events
