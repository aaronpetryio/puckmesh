-- Shots and the strength intervals rebuild manpower from the same penalties, one by event
-- order and one by clock, so their strength groups should agree. They can legitimately
-- differ in the second a penalty starts or a power-play goal ends one: a shot in that
-- second follows event order, an interval follows the clock. Warns on any mismatch so the
-- count shows in the build log; fails above 250 (about 1% of shots), which would mean the
-- two rules have drifted apart (docs/plans/metrics.md, step 4).
-- Returns the shots that disagree.
{{ config(warn_if='>0', error_if='>250') }}

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
)

select *
from matched
where strength_group != interval_strength_group
