with player_seasons as (
    select * from {{ ref('fct_player_seasons') }}
),

seasons as (
    select
        season_id,
        start_date
    from {{ ref('stg_pwhl__seasons') }}
),

priors as (
    select
        prior_group,
        prior_goals_per_xg,
        prior_xg
    from {{ ref('int_finishing_priors_estimated') }}
),

careers as (
    -- Sums of the season counts. Goaltending sums stay null for players who never played
    -- in net, since sum() skips the seasons' nulls.
    select
        player_seasons.league_id,
        player_seasons.player_id,
        player_seasons.season_type,
        max_by(player_seasons.position_group, seasons.start_date) as position_group,
        count(*) as seasons_played,
        sum(player_seasons.shots_on_goal) as shots_on_goal,
        sum(player_seasons.goals) as goals,
        sum(player_seasons.xg) as xg,
        sum(player_seasons.goalie_games) as goalie_games,
        sum(player_seasons.shots_faced) as shots_faced,
        sum(player_seasons.goals_allowed) as goals_allowed,
        sum(player_seasons.xg_faced) as xg_faced
    from player_seasons
    inner join seasons on player_seasons.season_id = seasons.season_id
    group by player_seasons.league_id, player_seasons.player_id, player_seasons.season_type
),

estimated as (
    -- The same shrinkage as fct_player_seasons, on career totals: under the model a
    -- player's skill is fixed, so a bigger sample just gets more weight.
    select
        careers.*,
        case
            when shooter_prior.prior_xg is null then shooter_prior.prior_goals_per_xg
            else
                (shooter_prior.prior_xg * shooter_prior.prior_goals_per_xg + careers.goals)
                / (shooter_prior.prior_xg + careers.xg)
        end as goals_per_xg_estimate,
        case
            when shooter_prior.prior_goals_per_xg is null then null
            when shooter_prior.prior_xg is null then 0.0
            else careers.xg / (shooter_prior.prior_xg + careers.xg)
        end as shrinkage_weight,
        case
            when careers.goalie_games is null then null
            when goalie_prior.prior_xg is null then goalie_prior.prior_goals_per_xg
            else
                (goalie_prior.prior_xg * goalie_prior.prior_goals_per_xg + careers.goals_allowed)
                / (goalie_prior.prior_xg + careers.xg_faced)
        end as goals_allowed_per_xg_estimate,
        case
            when careers.goalie_games is null or goalie_prior.prior_goals_per_xg is null
                then null
            when goalie_prior.prior_xg is null then 0.0
            else careers.xg_faced / (goalie_prior.prior_xg + careers.xg_faced)
        end as goalie_shrinkage_weight
    from careers
    left join priors as shooter_prior
        on careers.position_group = shooter_prior.prior_group
        and shooter_prior.prior_group in ('F', 'D')
    left join priors as goalie_prior on goalie_prior.prior_group = 'G'
)

select
    league_id,
    player_id,
    season_type,
    position_group,
    seasons_played,

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
