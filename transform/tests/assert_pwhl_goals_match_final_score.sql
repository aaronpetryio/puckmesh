-- Play-by-play goals should add up to each final game's score. A shootout winner gets
-- +1 on the scoreboard with no goal event, so shootout games may be off by exactly one.
-- Shootouts are detected from shootout attempts: the schedule's `shootout` flag misses
-- some (11 of 29 when this test was written).
-- Returns the games that don't reconcile.
with pbp as (
    select
        game_id,
        scoring_team_id,
        count(*) as goals
    from {{ ref('stg_pwhl__goals') }}
    group by all
),

shootout_games as (
    select distinct game_id
    from {{ ref('stg_pwhl__shootout_attempts') }}
)

select
    g.game_id,
    s.game_id is not null as had_shootout,
    g.home_goals,
    coalesce(h.goals, 0) as pbp_home_goals,
    g.away_goals,
    coalesce(a.goals, 0) as pbp_away_goals
from {{ ref('stg_pwhl__games') }} as g
left join pbp as h on h.game_id = g.game_id and h.scoring_team_id = g.home_team_id
left join pbp as a on a.game_id = g.game_id and a.scoring_team_id = g.away_team_id
left join shootout_games as s on s.game_id = g.game_id
where
    g.is_final
    and abs(g.home_goals - coalesce(h.goals, 0)) + abs(g.away_goals - coalesce(a.goals, 0))
    > case when s.game_id is not null then 1 else 0 end
