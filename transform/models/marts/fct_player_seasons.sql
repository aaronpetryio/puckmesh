with shots as (
    select
        league_id,
        season_id,
        season_type,
        shooter_player_id,
        is_goal,
        xg
    from {{ ref('fct_shots') }}
    -- Shots at a goalie that have xG, as in fct_goalie_games.
    where
        is_unblocked
        and not is_empty_net
        and xg is not null
        and season_type in ('regular', 'playoffs')
),

goalie_games as (
    select
        league_id,
        player_id,
        season_id,
        season_type,
        shots_faced,
        goals_allowed,
        xg_faced
    from {{ ref('fct_goalie_games') }}
),

player_team_seasons as (
    select
        player_id,
        season_id,
        team_id,
        position_group
    from {{ ref('fct_player_team_seasons') }}
),

players as (
    select
        player_id,
        position_group
    from {{ ref('dim_players') }}
),

priors as (
    select
        prior_group,
        prior_goals_per_xg,
        prior_xg
    from {{ ref('int_finishing_priors_estimated') }}
),

shooting as (
    select
        league_id,
        shooter_player_id as player_id,
        season_id,
        season_type,
        count(*) as shots_on_goal,
        count_if(is_goal) as goals,
        sum(xg) as xg
    from shots
    group by league_id, shooter_player_id, season_id, season_type
),

goaltending as (
    select
        league_id,
        player_id,
        season_id,
        season_type,
        count(*) as goalie_games,
        sum(shots_faced) as shots_faced,
        sum(goals_allowed) as goals_allowed,
        sum(xg_faced) as xg_faced
    from goalie_games
    group by league_id, player_id, season_id, season_type
),

player_seasons as (
    select
        coalesce(shooting.league_id, goaltending.league_id) as league_id,
        coalesce(shooting.player_id, goaltending.player_id) as player_id,
        coalesce(shooting.season_id, goaltending.season_id) as season_id,
        coalesce(shooting.season_type, goaltending.season_type) as season_type,
        coalesce(shooting.shots_on_goal, 0) as shots_on_goal,
        coalesce(shooting.goals, 0) as goals,
        coalesce(shooting.xg, 0) as xg,
        goaltending.goalie_games,
        goaltending.shots_faced,
        goaltending.goals_allowed,
        goaltending.xg_faced
    from shooting
    full outer join goaltending
        on shooting.player_id = goaltending.player_id
        and shooting.season_id = goaltending.season_id
),

season_positions as (
    select
        player_id,
        season_id,
        position_group
    from player_team_seasons
    -- Traded players have a row per team; team_id only makes the pick deterministic.
    qualify row_number() over (partition by player_id, season_id order by team_id asc) = 1
),

positioned as (
    -- Players missing from that season's roster fall back to their latest position.
    select
        player_seasons.*,
        coalesce(season_positions.position_group, players.position_group) as position_group
    from player_seasons
    left join season_positions
        on player_seasons.player_id = season_positions.player_id
        and player_seasons.season_id = season_positions.season_id
    left join players on player_seasons.player_id = players.player_id
),

estimated as (
    -- The best estimate of each player's multiplier on xG: (prior_xg * m + goals) /
    -- (prior_xg + xg), i.e. the player's record plus prior_xg expected goals at the group
    -- average m (docs/plans/metrics.md, step 2). A null prior_xg means the group shows no
    -- skill spread, so the estimate is m itself.
    select
        positioned.*,
        case
            when shooter_prior.prior_xg is null then shooter_prior.prior_goals_per_xg
            else
                (shooter_prior.prior_xg * shooter_prior.prior_goals_per_xg + positioned.goals)
                / (shooter_prior.prior_xg + positioned.xg)
        end as goals_per_xg_estimate,
        case
            when shooter_prior.prior_goals_per_xg is null then null
            when shooter_prior.prior_xg is null then 0.0
            else positioned.xg / (shooter_prior.prior_xg + positioned.xg)
        end as shrinkage_weight,
        case
            when positioned.goalie_games is null then null
            when goalie_prior.prior_xg is null then goalie_prior.prior_goals_per_xg
            else
                (goalie_prior.prior_xg * goalie_prior.prior_goals_per_xg + positioned.goals_allowed)
                / (goalie_prior.prior_xg + positioned.xg_faced)
        end as goals_allowed_per_xg_estimate,
        case
            when positioned.goalie_games is null or goalie_prior.prior_goals_per_xg is null
                then null
            when goalie_prior.prior_xg is null then 0.0
            else positioned.xg_faced / (goalie_prior.prior_xg + positioned.xg_faced)
        end as goalie_shrinkage_weight
    from positioned
    -- Skaters only: a goalie who took a shot has no shooting prior.
    left join priors as shooter_prior
        on positioned.position_group = shooter_prior.prior_group
        and shooter_prior.prior_group in ('F', 'D')
    left join priors as goalie_prior on goalie_prior.prior_group = 'G'
)

select
    league_id,
    player_id,
    season_id,
    season_type,
    position_group,

    shots_on_goal,
    goals,
    xg,
    goals - xg as goals_above_expected,
    xg * (goals_per_xg_estimate - 1) as goals_above_expected_shrunk,
    shrinkage_weight,

    goalie_games,
    shots_faced,
    goals_allowed,
    xg_faced,
    xg_faced - goals_allowed as gsax,
    100 * (xg_faced - goals_allowed) / nullif(shots_faced, 0) as gsax_per_100_shots,
    xg_faced * (1 - goals_allowed_per_xg_estimate) as gsax_shrunk,
    goalie_shrinkage_weight
from estimated
