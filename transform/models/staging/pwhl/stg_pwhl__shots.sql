with events as (
    select *
    from {{ ref('base_pwhl__play_by_play_events') }}
    where event_type in ('shot', 'blocked_shot')
)

select
    league_id,
    game_id,
    season_id,
    event_index,
    period,
    period_seconds,
    game_seconds,

    case
        when event_type = 'blocked_shot' then 'blocked'
        when
            nullif(event:game_goal_id::string, '') is not null
            or event:shot_quality_description::string ilike '%goal%' then 'goal'
        else 'on_net'
    end as shot_result,

    try_cast(event:player_id::string as int) as shooter_player_id,
    try_cast(event:player_team_id::string as int) as shooting_team_id,
    event:home::int = 1 as is_home_team,
    -- Null when the net was empty.
    try_cast(event:goalie_id::string as int) as goalie_player_id,
    try_cast(event:blocker_player_id::string as int) as blocker_player_id,

    -- Rink coordinates on a 600 x 300 grid, as recorded (not normalized for attacking direction).
    try_cast(event:x_location::string as int) as x_location,
    try_cast(event:y_location::string as int) as y_location,

    try_cast(event:shot_type::string as int) as shot_type_id,
    event:shot_type_description::string as shot_type,
    -- The league's own "quality chance" flag.
    event:shot_quality_description::string ilike 'quality%' as is_quality_chance,
    try_cast(event:game_goal_id::string as int) as goal_id,

    source_fetched_at
from events
