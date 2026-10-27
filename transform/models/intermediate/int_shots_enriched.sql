-- PWHL only today; other leagues' staging models will union in here.

with shots as (
    select * from {{ ref('stg_pwhl__shots') }}
),

goals as (
    select
        game_id,
        event_index,
        scoring_team_id
    from {{ ref('stg_pwhl__goals') }}
),

games as (
    select
        game_id,
        home_team_id,
        away_team_id
    from {{ ref('stg_pwhl__games') }}
),

attack_side as (
    -- The end each team attacked in each game-period, from its shots with a goalie in net.
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
    from shots
    where
        shot_result != 'blocked'
        and goalie_player_id is not null
    group by game_id, period, shooting_team_id
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
        shots.*,
        case
            when shots.shooting_team_id = games.home_team_id then games.away_team_id
            else games.home_team_id
        end as defending_team_id,
        -- A shot at a goalie is aimed at the nearer net. An empty-net shot can come from
        -- the shooter's own end, so it's aimed at the end its team attacked that period,
        -- falling back to home-attacks-left when the team has no other shots to go on.
        case
            when shots.goalie_player_id is null and shots.shot_result != 'blocked'
                then coalesce(attack_side.attacks_left, shots.is_home_team)
            else shots.x_location < {{ var('rink_center_x') }}
        end as is_toward_left_net
    from shots
    inner join games on shots.game_id = games.game_id
    left join attack_side
        on shots.game_id = attack_side.game_id
        and shots.period = attack_side.period
        and shots.shooting_team_id = attack_side.shooting_team_id
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
    ) as seconds_since_team_prev_shot
from positioned
inner join score_state
    on positioned.game_id = score_state.game_id
    and positioned.event_index = score_state.event_index
