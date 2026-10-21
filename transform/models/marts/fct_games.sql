-- One row per game, played or scheduled, with teams as named that season, the result,
-- and shot totals from play-by-play.
with games as (
    select * from {{ ref('stg_pwhl__games') }}
),

teams as (
    select * from {{ ref('stg_pwhl__teams') }}
),

shootouts as (
    -- The schedule's shootout flag misses some shootouts; attempts are the reliable signal.
    select
        game_id,
        max(case when is_winning_goal then shooting_team_id end) as shootout_winning_team_id
    from {{ ref('stg_pwhl__shootout_attempts') }}
    group by game_id
),

shot_totals as (
    select
        game_id,
        shooting_team_id,
        count_if(shot_result in ('on_net', 'goal')) as shots_on_goal,
        count(*)                                    as shot_attempts
    from {{ ref('stg_pwhl__shots') }}
    group by all
)

select
    games.league_id,
    games.game_id,
    games.season_id,
    seasons.season_type,
    games.game_date,
    games.scheduled_start_at,
    games.attendance,
    games.is_final,

    games.home_team_id,
    home.team_code                                      as home_team_code,
    home.team_name                                      as home_team_name,
    games.away_team_id,
    away.team_code                                      as away_team_code,
    away.team_name                                      as away_team_name,

    games.home_goals,
    games.away_goals,
    case
        when not games.is_final then null
        when games.home_goals > games.away_goals then games.home_team_id
        else games.away_team_id
    end                                                 as winning_team_id,
    case
        when not games.is_final then null
        when shootouts.game_id is not null then 'shootout'
        when games.went_to_overtime then 'overtime'
        else 'regulation'
    end                                                 as decision,
    games.went_to_overtime,
    shootouts.game_id is not null                       as went_to_shootout,
    shootouts.shootout_winning_team_id,

    home_shots.shots_on_goal                            as home_shots_on_goal,
    away_shots.shots_on_goal                            as away_shots_on_goal,
    home_shots.shot_attempts                            as home_shot_attempts,
    away_shots.shot_attempts                            as away_shot_attempts
from games
inner join {{ ref('stg_pwhl__seasons') }} as seasons using (season_id)
left join teams as home
    on home.team_id = games.home_team_id and home.season_id = games.season_id
left join teams as away
    on away.team_id = games.away_team_id and away.season_id = games.season_id
left join shootouts using (game_id)
left join shot_totals as home_shots
    on home_shots.game_id = games.game_id and home_shots.shooting_team_id = games.home_team_id
left join shot_totals as away_shots
    on away_shots.game_id = games.game_id and away_shots.shooting_team_id = games.away_team_id
