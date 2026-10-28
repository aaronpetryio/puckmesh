-- Skaters rebuilt from penalties and goalie pulls should match the players the league lists
-- on the ice for each goal (the lists count skaters, not goalies). Nothing in the rebuild
-- reads these lists, so they're an independent check. Goals with a list under 3 players are
-- skipped: about 2.5% have one side missing. A few lists disagree with the league's own
-- power-play flags, and goalie pulls for delayed penalties aren't recorded, so some
-- mismatches are expected: 37 of ~1,550 goals when this limit was set
-- (docs/plans/xg-audit.md, section 6). A jump past it means a rule broke.
-- Returns the goals that don't match.
{{ config(warn_if='>0', error_if='>45') }}

with shots as (
    select
        game_id,
        event_index,
        goal_id,
        skaters_for,
        skaters_against
    from {{ ref('fct_shots') }}
    where is_goal
),

goals as (
    select
        game_id,
        goal_id,
        size(on_ice_for_player_ids) as listed_for,
        size(on_ice_against_player_ids) as listed_against
    from {{ ref('stg_pwhl__goals') }}
)

select
    shots.game_id,
    shots.event_index,
    shots.skaters_for,
    shots.skaters_against,
    goals.listed_for,
    goals.listed_against
from shots
inner join goals
    on shots.game_id = goals.game_id
    and shots.goal_id = goals.goal_id
where
    goals.listed_for >= 3
    and goals.listed_against >= 3
    and (
        shots.skaters_for != goals.listed_for
        or shots.skaters_against != goals.listed_against
    )
