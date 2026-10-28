with penalties as (
    select * from {{ ref('stg_pwhl__penalties') }}
),

goals as (
    -- Only goals the league marks as power-play goals end a penalty early.
    select
        game_id,
        event_index,
        game_seconds,
        scoring_team_id
    from {{ ref('stg_pwhl__goals') }}
    where is_power_play
),

stoppages as (
    -- What else was called at the same moment, which decides whether coincidental
    -- penalties are served short-handed or replaced on the ice.
    select
        game_id,
        game_seconds,
        -- Misconducts sometimes carry the pp flag but never change strength.
        count_if(is_power_play_penalty and penalty_class != 'Misconduct') > 0
            as has_power_play_penalty,
        count(distinct case when penalty_class in ('Major', 'Match') then penalized_team_id end)
        > 1 as has_offsetting_majors
    from penalties
    where not coalesce(is_penalty_shot, false)
    group by game_id, game_seconds
),

counted as (
    -- Penalties that take a skater off the ice (docs/plans/xg-model.md, step 2; checked
    -- against the on-ice lists in xg-audit.md, 6c):
    -- - A minor with the pp flag always does.
    -- - Coincidental minors (no pp flag) give 4-on-4, unless a power-play penalty was called
    --   at the same moment; then they're replaced on the ice.
    -- - Majors and match penalties always do, whatever the pp flag says (a major with a game
    --   misconduct often has none), unless the other team got one at the same moment (a
    --   fight), when both are replaced.
    -- - Misconducts and penalty-shot penalties never do.
    select
        penalties.league_id,
        penalties.game_id,
        penalties.season_id,
        penalties.event_index,
        penalties.game_seconds,
        penalties.penalty_id,
        penalties.penalized_team_id,
        coalesce(
            penalties.served_by_player_id, penalties.penalized_player_id
        ) as serving_player_id,
        penalties.penalty_class = 'Minor' as is_minor,
        penalties.is_power_play_penalty,
        (penalties.penalty_minutes * 60)::int as duration_seconds
    from penalties
    inner join stoppages
        on penalties.game_id = stoppages.game_id
        and penalties.game_seconds = stoppages.game_seconds
    where
        not coalesce(penalties.is_penalty_shot, false)
        and (
            (
                penalties.penalty_class = 'Minor'
                and (penalties.is_power_play_penalty or not stoppages.has_power_play_penalty)
            )
            or (
                penalties.penalty_class in ('Major', 'Match')
                and not stoppages.has_offsetting_majors
            )
        )
),

numbered as (
    -- A double minor is recorded as two 2-minute minors on one player at the same moment,
    -- served back to back. Parts after the first start when the first one ends. A bench
    -- minor with no player named stands alone.
    select
        *,
        row_number() over (
            partition by
                game_id,
                penalized_team_id,
                coalesce(serving_player_id, -penalty_id),
                game_seconds,
                is_minor
            order by event_index
        ) as part_number,
        first_value(penalty_id) over (
            partition by
                game_id,
                penalized_team_id,
                coalesce(serving_player_id, -penalty_id),
                game_seconds,
                is_minor
            order by event_index
        ) as first_part_penalty_id
    from counted
),

first_parts as (
    select
        league_id,
        game_id,
        season_id,
        penalty_id,
        penalized_team_id,
        is_power_play_penalty,
        duration_seconds,
        is_minor and is_power_play_penalty as can_end_early,
        event_index as start_event_index,
        game_seconds as start_game_seconds,
        game_seconds + duration_seconds as end_game_seconds
    from numbered
    where not is_minor or part_number = 1
),

first_pass_picks as (
    -- Each power-play goal ends the minor, among those the other team is serving, that
    -- started first.
    select
        first_parts.penalty_id,
        goals.game_id,
        goals.event_index as goal_event_index
    from goals
    inner join first_parts
        on goals.game_id = first_parts.game_id
        and goals.scoring_team_id != first_parts.penalized_team_id
        and goals.event_index > first_parts.start_event_index
        and goals.game_seconds < first_parts.end_game_seconds
    where first_parts.can_end_early
    qualify row_number() over (
        partition by goals.game_id, goals.event_index
        order by first_parts.start_event_index
    ) = 1
),

first_pass_ends as (
    select
        penalty_id,
        min(goal_event_index) as ended_by_goal_event_index
    from first_pass_picks
    group by penalty_id
),

second_pass_picks as (
    -- The same pick again, now skipping minors an earlier goal already ended. Without this,
    -- two goals on a 5-on-3 would both pick the first minor and the second would never end.
    select
        first_parts.penalty_id,
        goals.game_id,
        goals.event_index as goal_event_index
    from goals
    inner join first_parts
        on goals.game_id = first_parts.game_id
        and goals.scoring_team_id != first_parts.penalized_team_id
        and goals.event_index > first_parts.start_event_index
        and goals.game_seconds < first_parts.end_game_seconds
    left join first_pass_ends on first_parts.penalty_id = first_pass_ends.penalty_id
    where
        first_parts.can_end_early
        and (
            first_pass_ends.ended_by_goal_event_index is null
            or goals.event_index <= first_pass_ends.ended_by_goal_event_index
        )
    qualify row_number() over (
        partition by goals.game_id, goals.event_index
        order by first_parts.start_event_index
    ) = 1
),

second_pass_ends as (
    select
        penalty_id,
        min(goal_event_index) as ended_by_goal_event_index
    from second_pass_picks
    group by penalty_id
),

first_parts_ended as (
    select
        first_parts.*,
        second_pass_ends.ended_by_goal_event_index,
        ending_goals.game_seconds as ended_at_game_seconds
    from first_parts
    left join second_pass_ends on first_parts.penalty_id = second_pass_ends.penalty_id
    left join goals as ending_goals
        on first_parts.game_id = ending_goals.game_id
        and second_pass_ends.ended_by_goal_event_index = ending_goals.event_index
),

later_parts as (
    -- Starts when the first part ends: its time running out, or the goal that ended it.
    select
        numbered.league_id,
        numbered.game_id,
        numbered.season_id,
        numbered.penalty_id,
        numbered.penalized_team_id,
        numbered.is_power_play_penalty,
        numbered.duration_seconds,
        numbered.is_power_play_penalty as can_end_early,
        coalesce(
            first_parts_ended.ended_by_goal_event_index, first_parts_ended.start_event_index
        ) as start_event_index,
        coalesce(
            first_parts_ended.ended_at_game_seconds, first_parts_ended.end_game_seconds
        ) as start_game_seconds
    from numbered
    inner join first_parts_ended
        on numbered.first_part_penalty_id = first_parts_ended.penalty_id
    where numbered.is_minor and numbered.part_number > 1
),

later_part_ends as (
    -- A goal ends one penalty, so goals that already ended a first part are skipped.
    select
        later_parts.penalty_id,
        min(goals.event_index) as ended_by_goal_event_index
    from later_parts
    inner join goals
        on later_parts.game_id = goals.game_id
        and later_parts.penalized_team_id != goals.scoring_team_id
        and later_parts.start_event_index < goals.event_index
        and later_parts.start_game_seconds <= goals.game_seconds
        and later_parts.start_game_seconds + later_parts.duration_seconds > goals.game_seconds
    left join second_pass_picks
        on goals.game_id = second_pass_picks.game_id
        and goals.event_index = second_pass_picks.goal_event_index
    where
        later_parts.can_end_early
        and second_pass_picks.penalty_id is null
    group by later_parts.penalty_id
)

select
    league_id,
    game_id,
    season_id,
    penalty_id,
    penalized_team_id,
    is_power_play_penalty,
    start_event_index,
    start_game_seconds,
    end_game_seconds,
    ended_by_goal_event_index
from first_parts_ended

union all

select
    later_parts.league_id,
    later_parts.game_id,
    later_parts.season_id,
    later_parts.penalty_id,
    later_parts.penalized_team_id,
    later_parts.is_power_play_penalty,
    later_parts.start_event_index,
    later_parts.start_game_seconds,
    later_parts.start_game_seconds + later_parts.duration_seconds as end_game_seconds,
    later_part_ends.ended_by_goal_event_index
from later_parts
left join later_part_ends on later_parts.penalty_id = later_part_ends.penalty_id
