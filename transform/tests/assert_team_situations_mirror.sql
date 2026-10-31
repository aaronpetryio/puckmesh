-- Every count for a team should be its opponent's count against, in the mirrored situation:
-- all and ev mirror themselves, pp mirrors pk. Adjusted counts too, since a shot's weight
-- is the same for both teams. A row with no mirror also fails.
-- Returns the team-game-situations that don't reconcile.
with situations as (
    select * from {{ ref('fct_team_game_situations') }}
),

mirrored as (
    select
        team.game_id,
        team.team_id,
        team.situation,
        opponent.team_id as opponent_row_team_id,
        team.shots_on_goal_for = opponent.shots_on_goal_against
        and team.shot_attempts_for = opponent.shot_attempts_against
        and team.quality_chances_for = opponent.quality_chances_against
        and team.goals_for = opponent.goals_against
        and abs(team.xg_for - opponent.xg_against) < 1e-6
        and equal_null(team.shots_on_goal_for_adjusted, opponent.shots_on_goal_against_adjusted)
        and equal_null(team.shot_attempts_for_adjusted, opponent.shot_attempts_against_adjusted)
        and equal_null(team.xg_for_adjusted, opponent.xg_against_adjusted)
        and equal_null(
            team.quality_chances_for_adjusted, opponent.quality_chances_against_adjusted
        ) as is_mirrored
    from situations as team
    left join situations as opponent
        on team.game_id = opponent.game_id
        and team.opponent_team_id = opponent.team_id
        and opponent.situation = case team.situation
            when 'pp' then 'pk'
            when 'pk' then 'pp'
            else team.situation
        end
)

select *
from mirrored
where
    opponent_row_team_id is null
    or not is_mirrored
