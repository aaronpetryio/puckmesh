-- One team's goals above expected is the other's below, so in each game the two teams'
-- goal_diff_above_expected should sum to 0 in the mirrored situation (pp with pk).
-- Returns the team-game-situations where they don't.
with situations as (
    select * from {{ ref('fct_team_game_situations') }}
)

select
    team.game_id,
    team.team_id,
    team.situation,
    team.goal_diff_above_expected + opponent.goal_diff_above_expected as total
from situations as team
inner join situations as opponent
    on team.game_id = opponent.game_id
    and team.opponent_team_id = opponent.team_id
    and opponent.situation = case team.situation
        when 'pp' then 'pk'
        when 'pk' then 'pp'
        else team.situation
    end
where abs(team.goal_diff_above_expected + opponent.goal_diff_above_expected) > 1e-6
