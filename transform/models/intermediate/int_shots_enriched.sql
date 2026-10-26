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
    -- The API mostly draws home shots toward the left net and away shots toward the
    -- right, but not always (~1.6% of team-periods are mixed). Use each team's majority
    -- side of unblocked shots per game-period.
    select
        game_id,
        period,
        shooting_team_id,
        avg(
            case when x_location < {{ var('rink_center_x') }} then 1.0 else 0.0 end
        ) >= 0.5 as attacks_left
    from shots
    where shot_result != 'blocked'
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
        -- Rotate 180 degrees when attacking left, so every shot attacks the net at x = rink_net_x.
        case
            when coalesce(attack_side.attacks_left, shots.is_home_team)
                then {{ var('rink_length_units') }} - shots.x_location
            else shots.x_location
        end as x_normalized,
        case
            when coalesce(attack_side.attacks_left, shots.is_home_team)
                then {{ var('rink_width_units') }} - shots.y_location
            else shots.y_location
        end as y_normalized
    from shots
    inner join games on shots.game_id = games.game_id
    left join attack_side
        on shots.game_id = attack_side.game_id
        and shots.period = attack_side.period
        and shots.shooting_team_id = attack_side.shooting_team_id
)

select
    located.*,

    round(sqrt(
        power(
            ({{ var('rink_net_x') }} - located.x_normalized)
            / {{ var('rink_units_per_foot') }},
            2
        )
        + power(
            (located.y_normalized - {{ var('rink_center_y') }})
            / {{ var('rink_units_per_foot') }},
            2
        )
    ), 1) as distance_ft,
    -- 0 = straight on; 90 = from the goal line; over 90 = from behind the net.
    round(degrees(atan2(
        abs(located.y_normalized - {{ var('rink_center_y') }}),
        {{ var('rink_net_x') }} - located.x_normalized
    )), 1) as angle_deg,

    score_state.goals_for_before,
    score_state.goals_against_before,
    score_state.goals_for_before - score_state.goals_against_before as score_diff,

    -- Time since this team's previous unblocked shot in the same period.
    located.game_seconds - lag(
        case when located.shot_result != 'blocked' then located.game_seconds end
    ) ignore nulls over (
        partition by located.game_id, located.shooting_team_id, located.period
        order by located.event_index
    ) as seconds_since_team_prev_shot
from located
inner join score_state
    on located.game_id = score_state.game_id
    and located.event_index = score_state.event_index
