-- A team's share and its opponent's share in the mirrored situation (pp with pk) should add
-- up to 1, raw and adjusted, wherever the share exists.
-- Returns the team-game-situations where they don't.
with situations as (
    select * from {{ ref('fct_team_game_situations') }}
),

paired as (
    select
        team.game_id,
        team.team_id,
        team.situation,
        team.shots_on_goal_share + opponent.shots_on_goal_share as shots_on_goal,
        team.shot_attempts_share + opponent.shot_attempts_share as shot_attempts,
        team.xg_share + opponent.xg_share as xg,
        team.quality_chance_share + opponent.quality_chance_share as quality_chances,
        team.shots_on_goal_share_adjusted + opponent.shots_on_goal_share_adjusted
            as shots_on_goal_adjusted,
        team.shot_attempts_share_adjusted + opponent.shot_attempts_share_adjusted
            as shot_attempts_adjusted,
        team.xg_share_adjusted + opponent.xg_share_adjusted as xg_adjusted,
        team.quality_chance_share_adjusted + opponent.quality_chance_share_adjusted
            as quality_chances_adjusted
    from situations as team
    inner join situations as opponent
        on team.game_id = opponent.game_id
        and team.opponent_team_id = opponent.team_id
        and opponent.situation = case team.situation
            when 'pp' then 'pk'
            when 'pk' then 'pp'
            else team.situation
        end
)

select *
from paired
-- A null sum means the share doesn't exist (no events); it's skipped.
where
    abs(shots_on_goal - 1) > 1e-9
    or abs(shot_attempts - 1) > 1e-9
    or abs(xg - 1) > 1e-9
    or abs(quality_chances - 1) > 1e-9
    or abs(shots_on_goal_adjusted - 1) > 1e-9
    or abs(shot_attempts_adjusted - 1) > 1e-9
    or abs(xg_adjusted - 1) > 1e-9
    or abs(quality_chances_adjusted - 1) > 1e-9
