-- A season year (the year the season ends) covers its preseason, regular season and
-- playoffs. Only regular-season and playoff games decide which venues are shared, so
-- preseason games at practice rinks and college arenas don't count.

with games as (
    select
        league_id,
        game_id,
        season_id,
        home_team_id,
        venue_id
    from {{ ref('stg_pwhl__games') }}
),

seasons as (
    select
        season_id,
        season_type,
        end_date
    from {{ ref('stg_pwhl__seasons') }}
),

located as (
    select
        games.*,
        seasons.season_type,
        year(seasons.end_date) as season_year
    from games
    inner join seasons on games.season_id = seasons.season_id
),

venue_teams as (
    select
        season_year,
        venue_id,
        count(distinct home_team_id) as home_teams_at_venue
    from located
    where
        season_type in ('regular', 'playoffs')
        and venue_id is not null
    group by season_year, venue_id
)

select
    located.league_id,
    located.game_id,
    located.home_team_id,
    located.season_year,
    located.venue_id,
    coalesce(venue_teams.home_teams_at_venue, 0) as home_teams_at_venue,
    -- Unknown venues, and venues only one team plays home games at, count as home.
    coalesce(
        venue_teams.home_teams_at_venue >= {{ var('neutral_site_min_home_teams') }}, false
    ) as is_neutral_site
from located
left join venue_teams
    on located.season_year = venue_teams.season_year
    and located.venue_id = venue_teams.venue_id
