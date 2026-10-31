with games as (
    select
        league_id,
        game_id,
        season_id,
        season_type,
        game_date,
        home_team_id,
        away_team_id,
        is_neutral_site
    from {{ ref('fct_games') }}
    -- xG covers the regular season and playoffs only.
    where
        is_final
        and season_type in ('regular', 'playoffs')
),

shots as (
    select
        game_id,
        event_index,
        shooting_team_id,
        defending_team_id,
        is_home_team,
        score_diff,
        strength_group,
        shot_result,
        is_goal,
        is_quality_chance,
        xg
    from {{ ref('fct_shots') }}
),

weights as (
    select * from {{ ref('int_score_venue_weights_estimated') }}
),

strength_intervals as (
    select
        game_id,
        duration_seconds,
        home_skaters,
        away_skaters
    from {{ ref('int_strength_intervals_derived') }}
),

situations as (
    select explode(array('all', 'ev', 'pp', 'pk')) as situation
),

team_games as (
    -- Both teams of every game with play-by-play.
    select
        games.*,
        games.home_team_id as team_id,
        games.away_team_id as opponent_team_id,
        true as is_home_team
    from games
    where games.game_id in (select shots.game_id from shots)

    union all

    select
        games.*,
        games.away_team_id as team_id,
        games.home_team_id as opponent_team_id,
        false as is_home_team
    from games
    where games.game_id in (select shots.game_id from shots)
),

weighted_shots as (
    -- Each shot's adjustment weight, from the shooting team's venue and its own score
    -- state. The same weight counts the shot for the shooter and against the defender.
    select
        shots.*,
        all_weights.weight_shots_on_goal as all_weight_shots_on_goal,
        all_weights.weight_shot_attempts as all_weight_shot_attempts,
        all_weights.weight_xg as all_weight_xg,
        all_weights.weight_quality_chances as all_weight_quality_chances,
        ev_weights.weight_shots_on_goal as ev_weight_shots_on_goal,
        ev_weights.weight_shot_attempts as ev_weight_shot_attempts,
        ev_weights.weight_xg as ev_weight_xg,
        ev_weights.weight_quality_chances as ev_weight_quality_chances
    from shots
    inner join games on shots.game_id = games.game_id
    left join weights as all_weights
        on all_weights.situation = 'all'
        and all_weights.shooter_venue = case
            when games.is_neutral_site then 'neutral'
            when shots.is_home_team then 'home'
            else 'away'
        end
        and all_weights.score_state = greatest(least(shots.score_diff, 2), -2)
    left join weights as ev_weights
        on ev_weights.situation = 'ev'
        and shots.strength_group = 'ev'
        and ev_weights.shooter_venue = case
            when games.is_neutral_site then 'neutral'
            when shots.is_home_team then 'home'
            else 'away'
        end
        and ev_weights.score_state = greatest(least(shots.score_diff, 2), -2)
),

credits as (
    -- Every shot counts for the shooting team and against the defending team, in all
    -- situations and in its own one. A shot on the power play (pp) is against a team on
    -- the penalty kill (pk). Shots with a net empty (en) count only in all.
    select
        shooting_team_id as team_id,
        'all' as situation,
        true as is_for,
        all_weight_shots_on_goal as weight_shots_on_goal,
        all_weight_shot_attempts as weight_shot_attempts,
        all_weight_xg as weight_xg,
        all_weight_quality_chances as weight_quality_chances,
        *
    from weighted_shots

    union all

    select
        defending_team_id as team_id,
        'all' as situation,
        false as is_for,
        all_weight_shots_on_goal as weight_shots_on_goal,
        all_weight_shot_attempts as weight_shot_attempts,
        all_weight_xg as weight_xg,
        all_weight_quality_chances as weight_quality_chances,
        *
    from weighted_shots

    union all

    select
        shooting_team_id as team_id,
        strength_group as situation,
        true as is_for,
        ev_weight_shots_on_goal as weight_shots_on_goal,
        ev_weight_shot_attempts as weight_shot_attempts,
        ev_weight_xg as weight_xg,
        ev_weight_quality_chances as weight_quality_chances,
        *
    from weighted_shots
    where strength_group != 'en'

    union all

    select
        defending_team_id as team_id,
        case strength_group when 'pp' then 'pk' when 'pk' then 'pp' else 'ev' end as situation,
        false as is_for,
        ev_weight_shots_on_goal as weight_shots_on_goal,
        ev_weight_shot_attempts as weight_shot_attempts,
        ev_weight_xg as weight_xg,
        ev_weight_quality_chances as weight_quality_chances,
        *
    from weighted_shots
    where strength_group != 'en'
),

totals as (
    select
        game_id,
        team_id,
        situation,
        count_if(is_for and shot_result != 'blocked') as shots_on_goal_for,
        count_if(not is_for and shot_result != 'blocked') as shots_on_goal_against,
        count_if(is_for) as shot_attempts_for,
        count_if(not is_for) as shot_attempts_against,
        coalesce(sum(case when is_for then xg end), 0) as xg_for,
        coalesce(sum(case when not is_for then xg end), 0) as xg_against,
        count_if(is_for and is_quality_chance) as quality_chances_for,
        count_if(not is_for and is_quality_chance) as quality_chances_against,
        count_if(is_for and is_goal) as goals_for,
        count_if(not is_for and is_goal) as goals_against,

        sum(case when is_for and shot_result != 'blocked' then weight_shots_on_goal end)
            as shots_on_goal_for_adjusted,
        sum(case when not is_for and shot_result != 'blocked' then weight_shots_on_goal end)
            as shots_on_goal_against_adjusted,
        sum(case when is_for then weight_shot_attempts end) as shot_attempts_for_adjusted,
        sum(case when not is_for then weight_shot_attempts end)
            as shot_attempts_against_adjusted,
        sum(case when is_for then xg * weight_xg end) as xg_for_adjusted,
        sum(case when not is_for then xg * weight_xg end) as xg_against_adjusted,
        sum(case when is_for and is_quality_chance then weight_quality_chances end)
            as quality_chances_for_adjusted,
        sum(case when not is_for and is_quality_chance then weight_quality_chances end)
            as quality_chances_against_adjusted
    from credits
    group by game_id, team_id, situation
),

team_seconds as (
    -- Time in each situation from each team's side; all is the whole game.
    select
        strength_intervals.game_id,
        team_games.team_id,
        case
            when team_games.is_home_team then strength_intervals.home_skaters
            else strength_intervals.away_skaters
        end as skaters_for,
        case
            when team_games.is_home_team then strength_intervals.away_skaters
            else strength_intervals.home_skaters
        end as skaters_against,
        strength_intervals.duration_seconds
    from strength_intervals
    inner join team_games on strength_intervals.game_id = team_games.game_id
),

situation_spans as (
    select
        game_id,
        team_id,
        case
            when skaters_for = skaters_against then 'ev'
            when skaters_for > skaters_against then 'pp'
            else 'pk'
        end as situation,
        duration_seconds
    from team_seconds

    union all

    select
        game_id,
        team_id,
        'all' as situation,
        duration_seconds
    from team_seconds
),

situation_totals as (
    select
        game_id,
        team_id,
        situation,
        sum(duration_seconds) as situation_seconds
    from situation_spans
    group by game_id, team_id, situation
),

filled as (
    -- One row per team, game and situation, with zeros where nothing happened (no power
    -- play in the game, say). Adjusted counts exist only for all and ev.
    select
        team_games.league_id,
        team_games.game_id,
        team_games.team_id,
        situations.situation,
        team_games.season_id,
        team_games.season_type,
        team_games.game_date,
        team_games.opponent_team_id,
        team_games.is_home_team,
        team_games.is_neutral_site,
        coalesce(situation_totals.situation_seconds, 0) as situation_seconds,

        coalesce(totals.shots_on_goal_for, 0) as shots_on_goal_for,
        coalesce(totals.shots_on_goal_against, 0) as shots_on_goal_against,
        coalesce(totals.shot_attempts_for, 0) as shot_attempts_for,
        coalesce(totals.shot_attempts_against, 0) as shot_attempts_against,
        coalesce(totals.xg_for, 0) as xg_for,
        coalesce(totals.xg_against, 0) as xg_against,
        coalesce(totals.quality_chances_for, 0) as quality_chances_for,
        coalesce(totals.quality_chances_against, 0) as quality_chances_against,
        coalesce(totals.goals_for, 0) as goals_for,
        coalesce(totals.goals_against, 0) as goals_against,

        situations.situation in ('all', 'ev') as is_adjusted,
        totals.shots_on_goal_for_adjusted,
        totals.shots_on_goal_against_adjusted,
        totals.shot_attempts_for_adjusted,
        totals.shot_attempts_against_adjusted,
        totals.xg_for_adjusted,
        totals.xg_against_adjusted,
        totals.quality_chances_for_adjusted,
        totals.quality_chances_against_adjusted
    from team_games
    cross join situations
    left join totals
        on team_games.game_id = totals.game_id
        and team_games.team_id = totals.team_id
        and situations.situation = totals.situation
    left join situation_totals
        on team_games.game_id = situation_totals.game_id
        and team_games.team_id = situation_totals.team_id
        and situations.situation = situation_totals.situation
),

adjusted as (
    select
        * except (
            shots_on_goal_for_adjusted,
            shots_on_goal_against_adjusted,
            shot_attempts_for_adjusted,
            shot_attempts_against_adjusted,
            xg_for_adjusted,
            xg_against_adjusted,
            quality_chances_for_adjusted,
            quality_chances_against_adjusted
        ),
        case when is_adjusted then coalesce(shots_on_goal_for_adjusted, 0) end
            as shots_on_goal_for_adjusted,
        case when is_adjusted then coalesce(shots_on_goal_against_adjusted, 0) end
            as shots_on_goal_against_adjusted,
        case when is_adjusted then coalesce(shot_attempts_for_adjusted, 0) end
            as shot_attempts_for_adjusted,
        case when is_adjusted then coalesce(shot_attempts_against_adjusted, 0) end
            as shot_attempts_against_adjusted,
        case when is_adjusted then coalesce(xg_for_adjusted, 0) end as xg_for_adjusted,
        case when is_adjusted then coalesce(xg_against_adjusted, 0) end as xg_against_adjusted,
        case when is_adjusted then coalesce(quality_chances_for_adjusted, 0) end
            as quality_chances_for_adjusted,
        case when is_adjusted then coalesce(quality_chances_against_adjusted, 0) end
            as quality_chances_against_adjusted
    from filled
)

select
    league_id,
    game_id,
    team_id,
    situation,
    season_id,
    season_type,
    game_date,
    opponent_team_id,
    is_home_team,
    is_neutral_site,
    situation_seconds,

    shots_on_goal_for,
    shots_on_goal_against,
    shot_attempts_for,
    shot_attempts_against,
    xg_for,
    xg_against,
    quality_chances_for,
    quality_chances_against,
    goals_for,
    goals_against,

    shots_on_goal_for / nullif(shots_on_goal_for + shots_on_goal_against, 0)
        as shots_on_goal_share,
    shot_attempts_for / nullif(shot_attempts_for + shot_attempts_against, 0)
        as shot_attempts_share,
    xg_for / nullif(xg_for + xg_against, 0) as xg_share,
    quality_chances_for / nullif(quality_chances_for + quality_chances_against, 0)
        as quality_chance_share,

    shots_on_goal_for_adjusted,
    shots_on_goal_against_adjusted,
    shot_attempts_for_adjusted,
    shot_attempts_against_adjusted,
    xg_for_adjusted,
    xg_against_adjusted,
    quality_chances_for_adjusted,
    quality_chances_against_adjusted,

    shots_on_goal_for_adjusted
    / nullif(shots_on_goal_for_adjusted + shots_on_goal_against_adjusted, 0)
        as shots_on_goal_share_adjusted,
    shot_attempts_for_adjusted
    / nullif(shot_attempts_for_adjusted + shot_attempts_against_adjusted, 0)
        as shot_attempts_share_adjusted,
    xg_for_adjusted / nullif(xg_for_adjusted + xg_against_adjusted, 0) as xg_share_adjusted,
    quality_chances_for_adjusted
    / nullif(quality_chances_for_adjusted + quality_chances_against_adjusted, 0)
        as quality_chance_share_adjusted,

    -- Per 2 minutes, the length of a minor: on the pp row, xG per full power play.
    120 * goals_for / nullif(situation_seconds, 0) as goals_for_per_2_min,
    120 * goals_against / nullif(situation_seconds, 0) as goals_against_per_2_min,
    120 * xg_for / nullif(situation_seconds, 0) as xg_for_per_2_min,
    120 * xg_against / nullif(situation_seconds, 0) as xg_against_per_2_min
from adjusted
