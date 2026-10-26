with games as (
    select * from {{ ref('stg_pwhl__games') }}
),

seasons as (
    select
        season_id,
        season_type
    from {{ ref('stg_pwhl__seasons') }}
),

teams as (
    select
        team_id,
        season_id,
        team_code,
        team_name
    from {{ ref('stg_pwhl__teams') }}
),

shootout_attempts as (
    select * from {{ ref('stg_pwhl__shootout_attempts') }}
),

shots as (
    select * from {{ ref('stg_pwhl__shots') }}
),

shootouts as (
    -- The schedule's shootout flag misses some shootouts; attempts are the reliable signal.
    select
        game_id,
        max(case when is_winning_goal then shooting_team_id end) as shootout_winning_team_id
    from shootout_attempts
    group by game_id
),

shot_totals as (
    select
        game_id,
        shooting_team_id,
        count_if(shot_result in ('on_net', 'goal')) as shots_on_goal,
        count(*) as shot_attempts
    from shots
    group by game_id, shooting_team_id
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
    home.team_code as home_team_code,
    home.team_name as home_team_name,
    games.away_team_id,
    away.team_code as away_team_code,
    away.team_name as away_team_name,

    games.home_goals,
    games.away_goals,
    case
        when not games.is_final then null
        when games.home_goals > games.away_goals then games.home_team_id
        else games.away_team_id
    end as winning_team_id,
    case
        when not games.is_final then null
        when shootouts.game_id is not null then 'shootout'
        when games.went_to_overtime then 'overtime'
        else 'regulation'
    end as decision,
    games.went_to_overtime,
    shootouts.game_id is not null as went_to_shootout,
    shootouts.shootout_winning_team_id,

    home_shots.shots_on_goal as home_shots_on_goal,
    away_shots.shots_on_goal as away_shots_on_goal,
    home_shots.shot_attempts as home_shot_attempts,
    away_shots.shot_attempts as away_shot_attempts
from games
inner join seasons on games.season_id = seasons.season_id
left join teams as home
    on games.home_team_id = home.team_id
    and games.season_id = home.season_id
left join teams as away
    on games.away_team_id = away.team_id
    and games.season_id = away.season_id
left join shootouts on games.game_id = shootouts.game_id
left join shot_totals as home_shots
    on games.game_id = home_shots.game_id
    and games.home_team_id = home_shots.shooting_team_id
left join shot_totals as away_shots
    on games.game_id = away_shots.game_id
    and games.away_team_id = away_shots.shooting_team_id
