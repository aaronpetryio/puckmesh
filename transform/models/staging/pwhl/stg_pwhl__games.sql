with source as (
    select
        payload:_meta.season_id::int as season_id,
        payload:_meta.fetched_at::timestamp as fetched_at,
        payload:response as response
    from {{ source('pwhl', 'schedule') }}
),

latest_fetch as (
    -- A season gets a new file whenever it changes; the newest has the current scores.
    select *
    from source
    qualify row_number() over (partition by season_id order by fetched_at desc) = 1
),

games as (
    select
        latest_fetch.fetched_at,
        g.value as game
    from latest_fetch,
        lateral variant_explode(latest_fetch.response:SiteKit.Schedule) as g
)

select
    'pwhl' as league_id,
    game:game_id::int as game_id,
    game:season_id::int as season_id,
    try_cast(game:game_number::string as int) as game_number,
    try_cast(game:date_played::string as date) as game_date,
    try_cast(game:GameDateISO8601::string as timestamp) as scheduled_start_at,
    game:timezone::string as venue_timezone,
    try_cast(game:location::string as int) as venue_id,

    game:home_team::int as home_team_id,
    game:home_team_code::string as home_team_code,
    game:visiting_team::int as away_team_id,
    game:visiting_team_code::string as away_team_code,

    game:final::int = 1 as is_final,
    game:game_status::string as game_status,
    -- The API reports 0-0 for games not yet played; only trust scores once final.
    case when game:final::int = 1 then game:home_goal_count::int end as home_goals,
    case when game:final::int = 1 then game:visiting_goal_count::int end as away_goals,
    game:overtime::int = 1 as went_to_overtime,
    game:shootout::int = 1 as went_to_shootout,
    try_cast(nullif(game:attendance::string, '') as int) as attendance,

    fetched_at as source_fetched_at
from games
