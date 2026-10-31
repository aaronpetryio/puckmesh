-- Neutral sites (Takeover Tour games) usually host games for several teams. A venue that
-- falls under neutral_site_min_home_games for its only home team that season year might
-- instead be that team's occasional second arena, wrongly flagged neutral. Warns so a
-- person can check it against the league's lists; it doesn't stop the build, because both
-- readings are possible (docs/plans/metrics.md, step 3).
-- Returns the venues to check.
{{ config(severity='warn') }}

with game_venues as (
    select * from {{ ref('int_game_venues_classified') }}
),

neutral_venues as (
    select
        season_year,
        venue_id,
        count(distinct home_team_id) as home_teams,
        min(home_team_id) as home_team_id,
        count(*) as games
    from game_venues
    where is_neutral_site
    group by season_year, venue_id
)

select
    season_year,
    venue_id,
    home_team_id,
    games
from neutral_venues
where home_teams = 1
