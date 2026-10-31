-- Score-and-venue adjustment, McCurdy's method (docs/plans/metrics.md, step 3). Across the
-- league, p(h) is the home team's share of a measure while the home team leads by h
-- (capped at +-2). From the shooting team's side, with its own lead d:
--   home:    expected share p(d)
--   away:    1 - p(-d), the mirror of the home team trailing by d
--   neutral: the average of the two, since there is no venue effect
-- Each event then counts 0.5 / expected share, so an average team's adjusted share is 0.5 in
-- every state. Neutral-site games are left out of the estimate.

with shots as (
    select
        game_id,
        event_index,
        season_id,
        is_home_team,
        score_diff,
        strength_group,
        shot_result,
        is_quality_chance
    from {{ ref('int_shots_enriched') }}
),

xg_predictions as (
    select
        game_id,
        event_index,
        xg
    from {{ ref('stg_ml__xg_predictions') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

game_venues as (
    select
        game_id,
        is_neutral_site
    from {{ ref('int_game_venues_classified') }}
),

events as (
    select
        shots.is_home_team,
        shots.strength_group,
        greatest(
            least(case when shots.is_home_team then shots.score_diff else -shots.score_diff end, 2),
            -2
        ) as home_score_state,
        case when shots.shot_result != 'blocked' then 1 else 0 end as shots_on_goal,
        1 as shot_attempts,
        coalesce(xg_predictions.xg, 0) as xg,
        case when shots.is_quality_chance then 1 else 0 end as quality_chances
    from shots
    inner join seasons on shots.season_id = seasons.season_id
    inner join game_venues on shots.game_id = game_venues.game_id
    left join xg_predictions
        on shots.game_id = xg_predictions.game_id
        and shots.event_index = xg_predictions.event_index
    where
        seasons.season_type in ('regular', 'playoffs')
        and not game_venues.is_neutral_site
),

situation_events as (
    select
        'all' as situation,
        *
    from events

    union all

    select
        'ev' as situation,
        *
    from events
    where strength_group = 'ev'
),

home_shares as (
    select
        situation,
        home_score_state,
        sum(case when is_home_team then shots_on_goal else 0 end) / nullif(sum(shots_on_goal), 0)
            as shots_on_goal,
        sum(case when is_home_team then shot_attempts else 0 end) / nullif(sum(shot_attempts), 0)
            as shot_attempts,
        sum(case when is_home_team then xg else 0 end) / nullif(sum(xg), 0) as xg,
        sum(case when is_home_team then quality_chances else 0 end)
        / nullif(sum(quality_chances), 0) as quality_chances
    from situation_events
    group by situation, home_score_state
),

paired as (
    -- Each home state next to its mirror: home up d next to home down d.
    select
        home.situation,
        home.home_score_state as score_state,
        home.shots_on_goal as home_shots_on_goal,
        home.shot_attempts as home_shot_attempts,
        home.xg as home_xg,
        home.quality_chances as home_quality_chances,
        1 - mirror.shots_on_goal as away_shots_on_goal,
        1 - mirror.shot_attempts as away_shot_attempts,
        1 - mirror.xg as away_xg,
        1 - mirror.quality_chances as away_quality_chances
    from home_shares as home
    inner join home_shares as mirror
        on home.situation = mirror.situation
        and home.home_score_state = -mirror.home_score_state
),

expected_shares as (
    select
        situation,
        'home' as shooter_venue,
        score_state,
        home_shots_on_goal as shots_on_goal,
        home_shot_attempts as shot_attempts,
        home_xg as xg,
        home_quality_chances as quality_chances
    from paired

    union all

    select
        situation,
        'away' as shooter_venue,
        score_state,
        away_shots_on_goal as shots_on_goal,
        away_shot_attempts as shot_attempts,
        away_xg as xg,
        away_quality_chances as quality_chances
    from paired

    union all

    select
        situation,
        'neutral' as shooter_venue,
        score_state,
        (home_shots_on_goal + away_shots_on_goal) / 2 as shots_on_goal,
        (home_shot_attempts + away_shot_attempts) / 2 as shot_attempts,
        (home_xg + away_xg) / 2 as xg,
        (home_quality_chances + away_quality_chances) / 2 as quality_chances
    from paired
)

select
    situation,
    shooter_venue,
    score_state,

    shots_on_goal as expected_share_shots_on_goal,
    shot_attempts as expected_share_shot_attempts,
    xg as expected_share_xg,
    quality_chances as expected_share_quality_chances,

    0.5 / nullif(shots_on_goal, 0) as weight_shots_on_goal,
    0.5 / nullif(shot_attempts, 0) as weight_shot_attempts,
    0.5 / nullif(xg, 0) as weight_xg,
    0.5 / nullif(quality_chances, 0) as weight_quality_chances
from expected_shares
