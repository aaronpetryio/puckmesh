-- A season year (the year the season ends) covers its preseason, regular season and
-- playoffs, so a team's few playoff home games are judged against its usual arenas.

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
        end_date
    from {{ ref('stg_pwhl__seasons') }}
),

located as (
    select
        games.*,
        year(seasons.end_date) as season_year
    from games
    inner join seasons on games.season_id = seasons.season_id
),

venue_counts as (
    select
        league_id,
        game_id,
        home_team_id,
        season_year,
        venue_id,
        count(*) over (partition by home_team_id, season_year, venue_id) as home_games_at_venue
    from located
)

select
    league_id,
    game_id,
    home_team_id,
    season_year,
    venue_id,
    home_games_at_venue,
    -- Unknown venues count as home: there's nothing to compare.
    coalesce(
        venue_id is not null
        and home_games_at_venue < {{ var('neutral_site_min_home_games') }},
        false
    ) as is_neutral_site
from venue_counts
