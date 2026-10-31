-- Shots and the strength intervals rebuild manpower from the same penalties, one by event
-- order and one by clock, so their strength groups should agree. They legitimately differ
-- in the second manpower changes: a power-play goal's own shot comes in the same second as
-- the goal that ends the penalty (still a power play by event order, the next interval by
-- clock), and a shot can come in the second a penalty is called. The first CI run had 402
-- such shots, so shots in a second where an interval starts are skipped. Everywhere else
-- the two rules must agree; the small allowance is for data quirks, and the warning shows
-- the count in the build log (docs/plans/metrics.md, step 4).
-- Returns the shots that disagree.
{{ config(warn_if='>0', error_if='>25') }}

with shots as (
    select
        game_id,
        event_index,
        game_seconds,
        is_home_team,
        strength_group
    from {{ ref('fct_shots') }}
    where strength_group != 'en'
),

strength_intervals as (
    select * from {{ ref('int_strength_intervals_derived') }}
),

matched as (
    select
        shots.game_id,
        shots.event_index,
        shots.game_seconds,
        shots.strength_group,
        case
            when strength_intervals.home_skaters = strength_intervals.away_skaters then 'ev'
            when
                (strength_intervals.home_skaters > strength_intervals.away_skaters)
                = shots.is_home_team
                then 'pp'
            else 'pk'
        end as interval_strength_group
    from shots
    inner join strength_intervals
        on shots.game_id = strength_intervals.game_id
        and shots.game_seconds >= strength_intervals.start_game_seconds
        and shots.game_seconds < strength_intervals.end_game_seconds
    -- Skip shots in a second where manpower changes (an interval starts there).
    where not exists (
        select 1
        from strength_intervals as manpower_changes
        where
            shots.game_id = manpower_changes.game_id
            and shots.game_seconds = manpower_changes.start_game_seconds
    )
)

select *
from matched
where strength_group != interval_strength_group
