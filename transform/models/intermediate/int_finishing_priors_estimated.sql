-- Gamma-Poisson empirical Bayes (docs/plans/metrics.md, step 2). Each player has a
-- multiplier on xG (goals per xG for shooters, goals allowed per xG faced for goalies) that
-- varies around the group average m with variance tau^2. Poisson noise alone would make
-- (goals - m * xG)^2 average m * xG, so the excess over that is the spread in skill:
--     tau^2 = (sum((goals - m * xg)^2) - m * sum(xg)) / sum(xg^2)
-- The prior is then worth prior_xg = m / tau^2 expected goals of average finishing.

with shots as (
    select
        league_id,
        game_id,
        event_index,
        season_id,
        shooter_player_id,
        goalie_player_id,
        shot_result,
        is_empty_net
    from {{ ref('int_shots_enriched') }}
),

xg_predictions as (
    select
        game_id,
        event_index,
        xg
    from {{ ref('stg_ml__xg_predictions') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

roster as (
    select
        player_id,
        season_id,
        team_id,
        position_group
    from {{ ref('stg_pwhl__roster_players') }}
),

scored_shots as (
    -- Shots at a goalie with xG, regular season only: playoffs are a few games between
    -- the best teams, and would tilt the average.
    select
        shots.league_id,
        shots.season_id,
        shots.shooter_player_id,
        shots.goalie_player_id,
        shots.shot_result = 'goal' as is_goal,
        xg_predictions.xg
    from shots
    inner join xg_predictions
        on shots.game_id = xg_predictions.game_id
        and shots.event_index = xg_predictions.event_index
    inner join seasons on shots.season_id = seasons.season_id
    where
        shots.shot_result != 'blocked'
        and not shots.is_empty_net
        and seasons.season_type = 'regular'
),

season_positions as (
    select
        player_id,
        season_id,
        position_group
    from roster
    -- A player traded mid-season has a row per team; team_id only makes the pick
    -- deterministic, as in dim_players.
    qualify row_number() over (partition by player_id, season_id order by team_id asc) = 1
),

shooter_seasons as (
    -- Shooters without a roster row that season are left out of the estimate.
    select
        scored_shots.league_id,
        season_positions.position_group as prior_group,
        count_if(scored_shots.is_goal) as goals,
        sum(scored_shots.xg) as xg
    from scored_shots
    inner join season_positions
        on scored_shots.shooter_player_id = season_positions.player_id
        and scored_shots.season_id = season_positions.season_id
    where season_positions.position_group in ('F', 'D')
    group by
        scored_shots.league_id,
        season_positions.position_group,
        scored_shots.shooter_player_id,
        scored_shots.season_id
),

goalie_seasons as (
    select
        league_id,
        'G' as prior_group,
        count_if(is_goal) as goals,
        sum(xg) as xg
    from scored_shots
    where goalie_player_id is not null
    group by league_id, goalie_player_id, season_id
),

player_seasons as (
    select * from shooter_seasons
    union all
    select * from goalie_seasons
),

group_means as (
    select
        league_id,
        prior_group,
        count(*) as player_seasons,
        sum(goals) / sum(xg) as prior_goals_per_xg
    from player_seasons
    group by league_id, prior_group
),

skill_spread as (
    select
        player_seasons.league_id,
        player_seasons.prior_group,
        group_means.player_seasons,
        group_means.prior_goals_per_xg,
        (
            sum(power(player_seasons.goals - group_means.prior_goals_per_xg * player_seasons.xg, 2))
            - group_means.prior_goals_per_xg * sum(player_seasons.xg)
        ) / sum(power(player_seasons.xg, 2)) as skill_variance
    from player_seasons
    inner join group_means
        on player_seasons.league_id = group_means.league_id
        and player_seasons.prior_group = group_means.prior_group
    group by
        player_seasons.league_id,
        player_seasons.prior_group,
        group_means.player_seasons,
        group_means.prior_goals_per_xg
)

select
    league_id,
    prior_group,
    player_seasons,
    prior_goals_per_xg,
    skill_variance,
    -- No spread beyond noise means no detectable skill: null, and everyone in the group is
    -- shrunk all the way to the average.
    case
        when skill_variance > 0 then prior_goals_per_xg / skill_variance
    end as prior_xg
from skill_spread
