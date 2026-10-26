-- Play-by-play goals should add up to each final game's score. A shootout winner gets
-- +1 on the scoreboard with no goal event, so shootout games may be off by exactly one.
-- Shootouts are detected from shootout attempts: the schedule's `shootout` flag misses
-- some (11 of 29 when this test was written).
-- Returns the games that don't reconcile.
with games as (
    select * from {{ ref('stg_pwhl__games') }}
),

goals as (
    select * from {{ ref('stg_pwhl__goals') }}
),

shootout_attempts as (
    select * from {{ ref('stg_pwhl__shootout_attempts') }}
),

pbp_goals as (
    select
        game_id,
        scoring_team_id,
        count(*) as goals
    from goals
    group by game_id, scoring_team_id
),

shootout_games as (
    select distinct game_id
    from shootout_attempts
)

select
    games.game_id,
    shootout_games.game_id is not null as has_shootout,
    games.home_goals,
    coalesce(home_pbp.goals, 0) as pbp_home_goals,
    games.away_goals,
    coalesce(away_pbp.goals, 0) as pbp_away_goals
from games
left join pbp_goals as home_pbp
    on games.game_id = home_pbp.game_id
    and games.home_team_id = home_pbp.scoring_team_id
left join pbp_goals as away_pbp
    on games.game_id = away_pbp.game_id
    and games.away_team_id = away_pbp.scoring_team_id
left join shootout_games on games.game_id = shootout_games.game_id
where
    games.is_final
    and abs(games.home_goals - coalesce(home_pbp.goals, 0))
    + abs(games.away_goals - coalesce(away_pbp.goals, 0))
    > case when shootout_games.game_id is not null then 1 else 0 end
