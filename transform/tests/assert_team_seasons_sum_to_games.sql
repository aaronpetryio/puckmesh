-- A team's season counts should be the sum of its game rows, per situation.
-- Returns the team-season-situations that don't reconcile.
with team_games as (
    select * from {{ ref('fct_team_game_situations') }}
),

team_seasons as (
    select * from {{ ref('fct_team_season_situations') }}
),

game_sums as (
    select
        team_id,
        season_id,
        situation,
        count(*) as games_played,
        sum(shot_attempts_for) as shot_attempts_for,
        sum(goals_against) as goals_against,
        sum(xg_for) as xg_for,
        sum(xg_against_adjusted) as xg_against_adjusted
    from team_games
    group by team_id, season_id, situation
)

select
    game_sums.team_id,
    game_sums.season_id,
    game_sums.situation
from game_sums
left join team_seasons
    on game_sums.team_id = team_seasons.team_id
    and game_sums.season_id = team_seasons.season_id
    and game_sums.situation = team_seasons.situation
where
    team_seasons.team_id is null
    or game_sums.games_played != team_seasons.games_played
    or game_sums.shot_attempts_for != team_seasons.shot_attempts_for
    or game_sums.goals_against != team_seasons.goals_against
    or abs(game_sums.xg_for - team_seasons.xg_for) > 1e-6
    or not equal_null(
        round(game_sums.xg_against_adjusted, 6), round(team_seasons.xg_against_adjusted, 6)
    )
