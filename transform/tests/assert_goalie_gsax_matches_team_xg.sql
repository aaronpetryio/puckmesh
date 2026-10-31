-- Each team's goalie GSAx in a game should add up to its xG against minus goals against,
-- counted from fct_shots on shots at a goalie that have xG. A gap means a shot was dropped
-- or counted against two goalies, e.g. a shot that names no goalie.
-- Returns the team-games that don't reconcile.
with goalie_games as (
    select
        game_id,
        team_id,
        gsax
    from {{ ref('fct_goalie_games') }}
),

shots as (
    select
        game_id,
        defending_team_id,
        is_goal,
        xg
    from {{ ref('fct_shots') }}
    where
        is_unblocked
        and not is_empty_net
        and xg is not null
        and season_type in ('regular', 'playoffs')
),

goalie_totals as (
    select
        game_id,
        team_id,
        sum(gsax) as gsax
    from goalie_games
    group by game_id, team_id
),

team_totals as (
    select
        game_id,
        defending_team_id as team_id,
        sum(xg) - count_if(is_goal) as xg_against_minus_goals_against
    from shots
    group by game_id, defending_team_id
)

select
    coalesce(team_totals.game_id, goalie_totals.game_id) as game_id,
    coalesce(team_totals.team_id, goalie_totals.team_id) as team_id,
    team_totals.xg_against_minus_goals_against,
    goalie_totals.gsax
from team_totals
full outer join goalie_totals
    on team_totals.game_id = goalie_totals.game_id
    and team_totals.team_id = goalie_totals.team_id
-- Goalies who faced no shots have gsax 0, so a missing team side counts as 0 too.
where
    abs(
        coalesce(team_totals.xg_against_minus_goals_against, 0)
        - coalesce(goalie_totals.gsax, 0)
    )
    > 1e-6
