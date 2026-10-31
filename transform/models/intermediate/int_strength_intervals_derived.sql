-- Manpower over time, from penalties alone (docs/plans/metrics.md, step 4). The same
-- skater rule as int_shots_enriched, applied to clock time instead of to shots; goalie
-- pulls are left out, as in strength_group. assert_shot_manpower_matches_intervals checks
-- that the two agree.

with games as (
    select
        league_id,
        game_id,
        season_id,
        home_team_id,
        away_team_id
    from {{ ref('stg_pwhl__games') }}
    where is_final
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

penalties as (
    select
        game_id,
        penalized_team_id,
        start_game_seconds,
        end_game_seconds,
        ended_by_goal_event_index
    from {{ ref('int_penalties_timed') }}
),

goals as (
    select
        game_id,
        event_index,
        period,
        game_seconds
    from {{ ref('stg_pwhl__goals') }}
),

shootout_games as (
    select distinct game_id
    from {{ ref('stg_pwhl__shootout_attempts') }}
),

overtime_goals as (
    -- The overtime winner: the game ends on it.
    select
        game_id,
        max(game_seconds) as game_seconds
    from goals
    where period > 3
    group by game_id
),

game_ends as (
    -- Regulation, or the overtime winner, or a full regular-season overtime before a
    -- shootout. Playoff games never go to a shootout.
    select
        games.*,
        seasons.season_type,
        case
            when overtime_goals.game_id is not null then overtime_goals.game_seconds
            when shootout_games.game_id is not null
                then
                    3 * {{ var('regulation_period_seconds') }}
                    + {{ var('regular_season_overtime_seconds') }}
            else 3 * {{ var('regulation_period_seconds') }}
        end as end_game_seconds
    from games
    inner join seasons on games.season_id = seasons.season_id
    left join overtime_goals on games.game_id = overtime_goals.game_id
    left join shootout_games on games.game_id = shootout_games.game_id
),

penalty_spans as (
    -- When each penalty really stops: its time running out, the power-play goal that ended
    -- it, or the end of the game.
    select
        penalties.game_id,
        penalties.penalized_team_id,
        penalties.start_game_seconds,
        least(
            penalties.end_game_seconds,
            coalesce(ending_goals.game_seconds, penalties.end_game_seconds),
            game_ends.end_game_seconds
        ) as end_game_seconds
    from penalties
    inner join game_ends on penalties.game_id = game_ends.game_id
    left join goals as ending_goals
        on penalties.game_id = ending_goals.game_id
        and penalties.ended_by_goal_event_index = ending_goals.event_index
    where penalties.start_game_seconds < game_ends.end_game_seconds
),

change_points as (
    -- Every moment manpower can change: the start, overtime (3-on-3 rules begin), each
    -- penalty's start and end, and the end of the game.
    select
        game_id,
        0 as game_seconds
    from game_ends

    union distinct

    select
        game_id,
        3 * {{ var('regulation_period_seconds') }} as game_seconds
    from game_ends
    where end_game_seconds > 3 * {{ var('regulation_period_seconds') }}

    union distinct

    select
        game_id,
        start_game_seconds as game_seconds
    from penalty_spans

    union distinct

    select
        game_id,
        end_game_seconds as game_seconds
    from penalty_spans

    union distinct

    select
        game_id,
        end_game_seconds as game_seconds
    from game_ends
),

intervals as (
    select
        game_id,
        game_seconds as start_game_seconds,
        lead(game_seconds) over (partition by game_id order by game_seconds) as end_game_seconds
    from change_points
),

penalty_counts as (
    -- Penalties being served through each interval. Change points include every start and
    -- end, so a penalty covers an interval exactly when it covers the interval's start.
    select
        intervals.game_id,
        intervals.start_game_seconds,
        count_if(penalty_spans.penalized_team_id = game_ends.home_team_id) as home_penalties,
        count_if(penalty_spans.penalized_team_id = game_ends.away_team_id) as away_penalties
    from intervals
    inner join game_ends on intervals.game_id = game_ends.game_id
    left join penalty_spans
        on intervals.game_id = penalty_spans.game_id
        and intervals.start_game_seconds >= penalty_spans.start_game_seconds
        and intervals.start_game_seconds < penalty_spans.end_game_seconds
    where intervals.end_game_seconds is not null
    group by intervals.game_id, intervals.start_game_seconds
),

situated as (
    select
        game_ends.league_id,
        game_ends.game_id,
        intervals.start_game_seconds,
        intervals.end_game_seconds,
        penalty_counts.home_penalties,
        penalty_counts.away_penalties,
        -- Regular-season and preseason overtime is 3-on-3 (see int_shots_enriched).
        game_ends.season_type in ('regular', 'preseason')
        and intervals.start_game_seconds >= 3 * {{ var('regulation_period_seconds') }}
            as is_three_on_three_overtime
    from intervals
    inner join game_ends on intervals.game_id = game_ends.game_id
    inner join penalty_counts
        on intervals.game_id = penalty_counts.game_id
        and intervals.start_game_seconds = penalty_counts.start_game_seconds
)

select
    league_id,
    game_id,
    start_game_seconds,
    end_game_seconds,
    end_game_seconds - start_game_seconds as duration_seconds,
    -- Same rule as int_shots_enriched: a penalty takes a skater off, never below 3; in
    -- 3-on-3 overtime it gives the other team an extra skater instead, up to 5.
    case
        when is_three_on_three_overtime
            then 3 + least(greatest(away_penalties - home_penalties, 0), 2)
        else 5 - least(home_penalties, 2)
    end as home_skaters,
    case
        when is_three_on_three_overtime
            then 3 + least(greatest(home_penalties - away_penalties, 0), 2)
        else 5 - least(away_penalties, 2)
    end as away_skaters
from situated
