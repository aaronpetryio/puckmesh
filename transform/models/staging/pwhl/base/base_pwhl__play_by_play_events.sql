with source as (
    select
        payload:_meta.season_id::int        as season_id,
        payload:_meta.game_id::int          as game_id,
        payload:_meta.fetched_at::timestamp as fetched_at,
        payload:response                    as response
    from {{ source('pwhl', 'play_by_play') }}
),

latest_fetch as (
    select *
    from source
    qualify row_number() over (partition by game_id order by fetched_at desc) = 1
),

events as (
    select
        latest_fetch.season_id,
        latest_fetch.game_id,
        latest_fetch.fetched_at,
        e.pos   as event_index,
        e.value as event
    from latest_fetch,
        lateral variant_explode(latest_fetch.response:GC.Pxpverbose) as e
),

timed as (
    select
        *,
        -- Period is `period_id` on some event types and `period` (sometimes "1st") on others.
        -- Shootout attempts have no period.
        coalesce(
            try_cast(event:period_id::string as int),
            try_cast(event:period::string as int)
        ) as period,
        -- `s` is seconds into the period on every event type except shootouts, where it
        -- counts attempts; the time strings vary in format, so `s` is the one to use.
        case
            when event:event::string != 'shootout' then try_cast(event:s::string as int)
        end as period_seconds
    from events
)

-- One row per play-by-play event, in API order. Event-specific fields stay in `event`
-- (VARIANT); the stg_pwhl__<event type> models type them.
select
    'pwhl'                                  as league_id,
    game_id,
    season_id,
    event_index,
    event:event::string                     as event_type,
    period,
    period_seconds,
    -- Regulation periods are 20 minutes; overtime starts at 3600 whatever its length.
    (period - 1) * 1200 + period_seconds    as game_seconds,
    event,
    fetched_at                              as source_fetched_at
from timed
