with team_games as (
    select * from {{ ref('fct_team_game_situations') }}
),

totals as (
    -- Counts are summed; shares are recomputed from the sums below, never averaged.
    -- Adjusted sums stay null for pp and pk, whose game rows are null.
    select
        league_id,
        team_id,
        season_id,
        situation,
        season_type,
        count(*) as games_played,
        sum(shots_on_goal_for) as shots_on_goal_for,
        sum(shots_on_goal_against) as shots_on_goal_against,
        sum(shot_attempts_for) as shot_attempts_for,
        sum(shot_attempts_against) as shot_attempts_against,
        sum(xg_for) as xg_for,
        sum(xg_against) as xg_against,
        sum(quality_chances_for) as quality_chances_for,
        sum(quality_chances_against) as quality_chances_against,
        sum(goals_for) as goals_for,
        sum(goals_against) as goals_against,
        sum(shots_on_goal_for_adjusted) as shots_on_goal_for_adjusted,
        sum(shots_on_goal_against_adjusted) as shots_on_goal_against_adjusted,
        sum(shot_attempts_for_adjusted) as shot_attempts_for_adjusted,
        sum(shot_attempts_against_adjusted) as shot_attempts_against_adjusted,
        sum(xg_for_adjusted) as xg_for_adjusted,
        sum(xg_against_adjusted) as xg_against_adjusted,
        sum(quality_chances_for_adjusted) as quality_chances_for_adjusted,
        sum(quality_chances_against_adjusted) as quality_chances_against_adjusted
    from team_games
    group by league_id, team_id, season_id, situation, season_type
)

select
    league_id,
    team_id,
    season_id,
    situation,
    season_type,
    games_played,

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
        as quality_chance_share_adjusted
from totals
