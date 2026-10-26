with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type = 'goal'
)

select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    try_cast(event:id::string as int) as goal_id,
    try_cast(event:team_id::string as int) as scoring_team_id,
    event:home::int = 1 as is_home_team,
    try_cast(event:goal_player_id::string as int) as scorer_player_id,
    try_cast(event:assist1_player_id::string as int) as primary_assist_player_id,
    try_cast(event:assist2_player_id::string as int) as secondary_assist_player_id,

    event:power_play::int = 1 as is_power_play,
    event:short_handed::int = 1 as is_short_handed,
    event:empty_net::int = 1 as is_empty_net,
    event:penalty_shot::int = 1 as is_penalty_shot,
    event:game_winning::int = 1 as is_game_winning,
    event:game_tieing::int = 1 as is_game_tying,
    event:insurance_goal::int = 1 as is_insurance,

    try_cast(event:x_location::string as int) as x_location,
    try_cast(event:y_location::string as int) as y_location,

    -- Skaters on the ice: `plus` for the scoring team, `minus` for the other.
    transform(
        try_variant_get(event, '$.plus', 'array<variant>'),
        p -> p:player_id::int
    ) as on_ice_for_player_ids,
    transform(
        try_variant_get(event, '$.minus', 'array<variant>'),
        p -> p:player_id::int
    ) as on_ice_against_player_ids,

    source_fetched_at
from events
