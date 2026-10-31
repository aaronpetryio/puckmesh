with games as (
    select
        game_id,
        season_id,
        season_type,
        game_date,
        home_team_id,
        away_team_id
    from {{ ref('fct_games') }}
    -- Only these are scored for xG (docs/plans/xg-model.md, step 3).
    where season_type in ('regular', 'playoffs')
),

shots as (
    select
        league_id,
        game_id,
        event_index,
        defending_team_id,
        goalie_player_id,
        is_goal,
        xg
    from {{ ref('fct_shots') }}
    -- Shots at a goalie that have xG. Unscored shots (new ones waiting for the next scoring
    -- run) are left out of both goals and xG, so GSAx always compares like with like.
    where
        is_unblocked
        and not is_empty_net
        and xg is not null
),

goalie_changes as (
    select
        league_id,
        game_id,
        event_index,
        team_id,
        goalie_in_player_id
    from {{ ref('stg_pwhl__goalie_changes') }}
    where goalie_in_player_id is not null
),

appearances as (
    -- Every goalie who went in net. The first goalie in for each team is the starter; later
    -- rows are relief appearances, or the same goalie returning after a pull.
    select distinct
        league_id,
        game_id,
        goalie_in_player_id as player_id,
        team_id
    from goalie_changes
),

starters as (
    select
        game_id,
        team_id,
        min_by(goalie_in_player_id, event_index) as player_id
    from goalie_changes
    group by game_id, team_id
),

shot_totals as (
    select
        league_id,
        game_id,
        goalie_player_id as player_id,
        defending_team_id as team_id,
        count(*) as shots_faced,
        count_if(is_goal) as goals_allowed,
        sum(xg) as xg_faced
    from shots
    where goalie_player_id is not null
    group by league_id, game_id, goalie_player_id, defending_team_id
),

goalie_games as (
    -- A goalie who faced a shot but has no recorded goalie change still gets a row.
    select
        coalesce(appearances.league_id, shot_totals.league_id) as league_id,
        coalesce(appearances.game_id, shot_totals.game_id) as game_id,
        coalesce(appearances.player_id, shot_totals.player_id) as player_id,
        coalesce(appearances.team_id, shot_totals.team_id) as team_id,
        coalesce(shot_totals.shots_faced, 0) as shots_faced,
        coalesce(shot_totals.goals_allowed, 0) as goals_allowed,
        coalesce(shot_totals.xg_faced, 0) as xg_faced
    from appearances
    full outer join shot_totals
        on appearances.game_id = shot_totals.game_id
        and appearances.player_id = shot_totals.player_id
        and appearances.team_id = shot_totals.team_id
)

select
    goalie_games.league_id,
    goalie_games.game_id,
    goalie_games.player_id,
    games.season_id,
    games.season_type,
    games.game_date,

    goalie_games.team_id,
    case
        when goalie_games.team_id = games.home_team_id then games.away_team_id
        else games.home_team_id
    end as opponent_team_id,
    goalie_games.team_id = games.home_team_id as is_home_team,
    coalesce(goalie_games.player_id = starters.player_id, false) as is_starter,

    goalie_games.shots_faced,
    goalie_games.goals_allowed,
    goalie_games.xg_faced,
    goalie_games.xg_faced - goalie_games.goals_allowed as gsax,
    100 * (goalie_games.xg_faced - goalie_games.goals_allowed)
    / nullif(goalie_games.shots_faced, 0) as gsax_per_100_shots
from goalie_games
inner join games on goalie_games.game_id = games.game_id
left join starters
    on goalie_games.game_id = starters.game_id
    and goalie_games.team_id = starters.team_id
