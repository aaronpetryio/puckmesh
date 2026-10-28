-- PWHL only today; other leagues' staging models will union in here.

with shots as (
    select * from {{ ref('stg_pwhl__shots') }}
),

goals as (
    select
        game_id,
        event_index,
        goal_id,
        scoring_team_id,
        is_empty_net
    from {{ ref('stg_pwhl__goals') }}
),

games as (
    select
        game_id,
        home_team_id,
        away_team_id
    from {{ ref('stg_pwhl__games') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

penalties as (
    select * from {{ ref('int_penalties_timed') }}
),

goalie_changes as (
    select
        game_id,
        event_index,
        period,
        team_id,
        goalie_in_player_id
    from {{ ref('stg_pwhl__goalie_changes') }}
),

flagged as (
    -- HockeyTech flags an empty net only on the goal event; the shot event usually still
    -- names the pulled goalie, so a missing goalie_player_id finds ~1 in 10 empty-net goals
    -- (docs/plans/xg-audit.md, query 5a). A shot on goal at an empty net always scores,
    -- so only goals can be empty-net shots.
    select
        shots.*,
        shots.shot_result = 'goal' and coalesce(goals.is_empty_net, false) as is_empty_net
    from shots
    left join goals
        on shots.game_id = goals.game_id
        and shots.goal_id = goals.goal_id
),

attack_side as (
    -- The end each team attacked in each game-period, from its unblocked shots other than
    -- empty-net goals.
    -- HockeyTech draws the home team attacking left, but scorers swapped the ends for whole
    -- periods in ~1.5% of game-periods (game 3, periods 1 and 3, matches the league's own
    -- shot chart), so empty-net shots use this rather than home/away.
    select
        game_id,
        period,
        shooting_team_id,
        avg(
            case when x_location < {{ var('rink_center_x') }} then 1.0 else 0.0 end
        ) >= 0.5 as attacks_left
    from flagged
    where
        shot_result != 'blocked'
        and not is_empty_net
    group by game_id, period, shooting_team_id
),

penalty_counts as (
    -- Penalties being served at each shot, by team. A penalty covers the events after it
    -- was called and before it ends: its time running out, or the goal that ended it.
    select
        flagged.game_id,
        flagged.event_index,
        count_if(penalties.penalized_team_id = flagged.shooting_team_id) as own_penalties,
        count_if(penalties.penalized_team_id != flagged.shooting_team_id) as other_penalties
    from flagged
    inner join penalties
        on flagged.game_id = penalties.game_id
        and flagged.event_index > penalties.start_event_index
        and flagged.game_seconds >= penalties.start_game_seconds
        and flagged.game_seconds < penalties.end_game_seconds
        and (
            penalties.ended_by_goal_event_index is null
            or flagged.event_index < penalties.ended_by_goal_event_index
        )
    group by flagged.game_id, flagged.event_index
),

goalie_change_windows as (
    select
        *,
        lead(event_index) over (
            partition by game_id, team_id
            order by event_index
        ) as next_change_event_index
    from goalie_changes
),

goalie_pulls as (
    select
        game_id,
        team_id,
        period,
        event_index as start_event_index,
        next_change_event_index
    from goalie_change_windows
    where goalie_in_player_id is null
),

goalie_returns as (
    -- The first shot against the team that shows its goalie back in net: a save, or a goal
    -- that wasn't into an empty net. Returns often aren't recorded as goalie changes
    -- (docs/plans/xg-audit.md, 6a: 74 saves were credited to a team we had as pulled).
    select
        goalie_pulls.game_id,
        goalie_pulls.team_id,
        goalie_pulls.start_event_index,
        min(flagged.event_index) as goalie_seen_event_index
    from goalie_pulls
    inner join flagged
        on goalie_pulls.game_id = flagged.game_id
        and goalie_pulls.period = flagged.period
        and goalie_pulls.team_id != flagged.shooting_team_id
        and goalie_pulls.start_event_index < flagged.event_index
    where
        flagged.shot_result = 'on_net'
        or (flagged.shot_result = 'goal' and not flagged.is_empty_net)
    group by goalie_pulls.game_id, goalie_pulls.team_id, goalie_pulls.start_event_index
),

empty_net_windows as (
    -- A net is empty from a goalie change with nobody coming in until the team's next
    -- change or the goalie is seen back in net, whichever comes first (least() skips
    -- nulls). Kept within the period.
    select
        goalie_pulls.game_id,
        goalie_pulls.team_id,
        goalie_pulls.period,
        goalie_pulls.start_event_index,
        least(
            goalie_pulls.next_change_event_index, goalie_returns.goalie_seen_event_index
        ) as end_event_index
    from goalie_pulls
    left join goalie_returns
        on goalie_pulls.game_id = goalie_returns.game_id
        and goalie_pulls.team_id = goalie_returns.team_id
        and goalie_pulls.start_event_index = goalie_returns.start_event_index
),

pull_counts as (
    select
        flagged.game_id,
        flagged.event_index,
        count_if(empty_net_windows.team_id = flagged.shooting_team_id) > 0 as is_own_net_empty,
        count_if(empty_net_windows.team_id != flagged.shooting_team_id) > 0
            as is_other_net_empty
    from flagged
    inner join empty_net_windows
        on flagged.game_id = empty_net_windows.game_id
        and flagged.period = empty_net_windows.period
        and flagged.event_index > empty_net_windows.start_event_index
        and (
            empty_net_windows.end_event_index is null
            or flagged.event_index < empty_net_windows.end_event_index
        )
    group by flagged.game_id, flagged.event_index
),

situation as (
    select
        flagged.game_id,
        flagged.event_index,
        -- Overtime is 3-on-3 outside the playoffs, preseason included (xg-audit.md, 6a).
        coalesce(seasons.season_type != 'playoffs' and flagged.period > 3, false)
            as is_three_on_three_overtime,
        coalesce(penalty_counts.own_penalties, 0) as own_penalties,
        coalesce(penalty_counts.other_penalties, 0) as other_penalties,
        coalesce(pull_counts.is_own_net_empty, false) as is_own_net_empty,
        -- An empty-net goal means the other team had pulled its goalie, even when the
        -- change wasn't recorded (e.g. for a delayed penalty).
        coalesce(pull_counts.is_other_net_empty, false) or flagged.is_empty_net
            as is_other_net_empty
    from flagged
    left join seasons on flagged.season_id = seasons.season_id
    left join penalty_counts
        on flagged.game_id = penalty_counts.game_id
        and flagged.event_index = penalty_counts.event_index
    left join pull_counts
        on flagged.game_id = pull_counts.game_id
        and flagged.event_index = pull_counts.event_index
),

strength as (
    -- Skaters on the ice for each side (docs/plans/xg-model.md, step 2). In regulation and
    -- playoff overtime each penalty takes a skater off, never below 3. Other overtime is
    -- 3-on-3, and a penalty gives the other team an extra skater instead, up to 5. A
    -- pulled goalie adds a skater.
    select
        game_id,
        event_index,
        case
            when is_three_on_three_overtime
                then 3 + least(greatest(other_penalties - own_penalties, 0), 2)
            else 5 - least(own_penalties, 2)
        end
        + case when is_own_net_empty then 1 else 0 end as skaters_for,
        case
            when is_three_on_three_overtime
                then 3 + least(greatest(own_penalties - other_penalties, 0), 2)
            else 5 - least(other_penalties, 2)
        end
        + case when is_other_net_empty then 1 else 0 end as skaters_against
    from situation
),

score_state as (
    -- Events are in time order and each goal is listed right after its shot, so goals
    -- with a lower event_index are exactly the goals scored before this shot.
    select
        shots.game_id,
        shots.event_index,
        count_if(goals.scoring_team_id = shots.shooting_team_id) as goals_for_before,
        count_if(goals.scoring_team_id != shots.shooting_team_id) as goals_against_before
    from shots
    left join goals
        on shots.game_id = goals.game_id
        and shots.event_index > goals.event_index
    group by shots.game_id, shots.event_index
),

located as (
    select
        flagged.*,
        case
            when flagged.shooting_team_id = games.home_team_id then games.away_team_id
            else games.home_team_id
        end as defending_team_id,
        -- A shot at a goalie is aimed at the nearer net. An empty-net shot can come from
        -- the shooter's own end, so it's aimed at the end its team attacked that period,
        -- falling back to home-attacks-left when the team has no other shots to go on.
        case
            when flagged.is_empty_net
                then coalesce(attack_side.attacks_left, flagged.is_home_team)
            else flagged.x_location < {{ var('rink_center_x') }}
        end as is_toward_left_net
    from flagged
    inner join games on flagged.game_id = games.game_id
    left join attack_side
        on flagged.game_id = attack_side.game_id
        and flagged.period = attack_side.period
        and flagged.shooting_team_id = attack_side.shooting_team_id
),

positioned as (
    -- The grid is the whole rink stretched to fit, so the axes have different scales
    -- (3 units/ft along, ~3.53 across). Feet run from center ice, positive y toward the
    -- top of the grid. Turning a shot at the left net 180 degrees (both signs flip) puts
    -- every shot at the net at x = +rink_goal_line_ft.
    select
        located.*,
        case when located.is_toward_left_net then -1 else 1 end
        * (
            located.x_location * {{ var('rink_length_ft') }} / {{ var('rink_length_units') }}
            - {{ var('rink_length_ft') }} / 2
        ) as x_ft,
        case when located.is_toward_left_net then -1 else 1 end
        * (
            {{ var('rink_width_ft') }} / 2
            - located.y_location * {{ var('rink_width_ft') }} / {{ var('rink_width_units') }}
        ) as y_ft
    from located
)

select
    -- Distance and angle use the unrounded feet; only the output columns are rounded.
    positioned.* except (is_toward_left_net, x_ft, y_ft),
    round(positioned.x_ft, 1) as x_ft,
    round(positioned.y_ft, 1) as y_ft,

    round(sqrt(
        power({{ var('rink_goal_line_ft') }} - positioned.x_ft, 2)
        + power(positioned.y_ft, 2)
    ), 1) as distance_ft,
    -- 0 = straight on; 90 = from the goal line; over 90 = from behind the net.
    round(degrees(atan2(
        abs(positioned.y_ft),
        {{ var('rink_goal_line_ft') }} - positioned.x_ft
    )), 1) as angle_deg,

    score_state.goals_for_before,
    score_state.goals_against_before,
    score_state.goals_for_before - score_state.goals_against_before as score_diff,

    -- Time since this team's previous unblocked shot in the same period.
    positioned.game_seconds - lag(
        case when positioned.shot_result != 'blocked' then positioned.game_seconds end
    ) ignore nulls over (
        partition by positioned.game_id, positioned.shooting_team_id, positioned.period
        order by positioned.event_index
    ) as seconds_since_team_prev_shot,

    strength.skaters_for,
    strength.skaters_against,
    concat(strength.skaters_for, 'v', strength.skaters_against) as strength_state
from positioned
inner join score_state
    on positioned.game_id = score_state.game_id
    and positioned.event_index = score_state.event_index
inner join strength
    on positioned.game_id = strength.game_id
    and positioned.event_index = strength.event_index
