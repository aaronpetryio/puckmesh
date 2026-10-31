-- A team's all-situations row should agree with the game: shots on goal and shot attempts
-- with fct_games' play-by-play counts, and goals with the goal events (penalty-shot goals
-- left out, as they aren't shot events).
-- Returns the team-games that don't reconcile.
with situations as (
    select
        game_id,
        team_id,
        shots_on_goal_for,
        shot_attempts_for,
        goals_for
    from {{ ref('fct_team_game_situations') }}
    where situation = 'all'
),

games as (
    select
        game_id,
        home_team_id,
        away_team_id,
        home_shots_on_goal,
        away_shots_on_goal,
        home_shot_attempts,
        away_shot_attempts
    from {{ ref('fct_games') }}
),

game_teams as (
    -- fct_games' counts for each team. They're null for a team with no shot attempts.
    select
        game_id,
        home_team_id as team_id,
        coalesce(home_shots_on_goal, 0) as shots_on_goal,
        coalesce(home_shot_attempts, 0) as shot_attempts
    from games

    union all

    select
        game_id,
        away_team_id as team_id,
        coalesce(away_shots_on_goal, 0) as shots_on_goal,
        coalesce(away_shot_attempts, 0) as shot_attempts
    from games
),

goals as (
    select
        game_id,
        scoring_team_id,
        count(*) as goals
    from {{ ref('stg_pwhl__goals') }}
    where not coalesce(is_penalty_shot, false)
    group by game_id, scoring_team_id
)

select
    situations.game_id,
    situations.team_id,
    situations.shots_on_goal_for,
    situations.shot_attempts_for,
    situations.goals_for,
    coalesce(goals.goals, 0) as goal_events
from situations
inner join game_teams
    on situations.game_id = game_teams.game_id
    and situations.team_id = game_teams.team_id
left join goals
    on situations.game_id = goals.game_id
    and situations.team_id = goals.scoring_team_id
where
    situations.shots_on_goal_for != game_teams.shots_on_goal
    or situations.shot_attempts_for != game_teams.shot_attempts
    or situations.goals_for != coalesce(goals.goals, 0)
