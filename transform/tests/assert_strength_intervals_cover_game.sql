-- Each final game's intervals should tile it: the first starts at 0, each starts where the
-- one before ended, and they add up to the game's length.
-- Returns the games that don't.
with strength_intervals as (
    select * from {{ ref('int_strength_intervals_derived') }}
),

ordered as (
    select
        game_id,
        start_game_seconds,
        end_game_seconds,
        duration_seconds,
        lag(end_game_seconds) over (partition by game_id order by start_game_seconds)
            as previous_end_game_seconds
    from strength_intervals
),

per_game as (
    select
        game_id,
        min(start_game_seconds) as first_start,
        max(end_game_seconds) as last_end,
        sum(duration_seconds) as total_seconds,
        count_if(
            previous_end_game_seconds is not null
            and previous_end_game_seconds != start_game_seconds
        ) as gaps
    from ordered
    group by game_id
)

select *
from per_game
where
    first_start != 0
    or gaps > 0
    or total_seconds != last_end
    or last_end < 3 * {{ var('regulation_period_seconds') }}
