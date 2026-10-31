-- A team's ev, pp and pk seconds should add up to its all seconds, the game's length.
-- Returns the team-games where they don't.
with situations as (
    select
        game_id,
        team_id,
        situation,
        situation_seconds
    from {{ ref('fct_team_game_situations') }}
)

select
    game_id,
    team_id,
    sum(case when situation = 'all' then situation_seconds else 0 end) as all_seconds,
    sum(case when situation != 'all' then situation_seconds else 0 end) as situation_seconds
from situations
group by game_id, team_id
having
    sum(case when situation = 'all' then situation_seconds else 0 end)
    != sum(case when situation != 'all' then situation_seconds else 0 end)
