with source as (
    select
        payload:_meta.season_id::int as season_id,
        payload:_meta.fetched_at::timestamp as fetched_at,
        payload:response as response
    from {{ source('pwhl', 'teams') }}
),

latest_fetch as (
    select *
    from source
    qualify row_number() over (partition by season_id order by fetched_at desc) = 1
),

teams as (
    select
        latest_fetch.season_id,
        latest_fetch.fetched_at,
        t.value as team
    from latest_fetch,
        lateral variant_explode(latest_fetch.response:SiteKit.Teamsbyseason) as t
)

select
    'pwhl' as league_id,
    team:id::int as team_id,
    season_id,
    team:code::string as team_code,
    team:name::string as team_name,
    nullif(team:city::string, '') as city,
    nullif(team:nickname::string, '') as nickname,
    -- HockeyTech calls conferences "divisions".
    try_cast(team:division_id::string as int) as conference_id,
    nullif(team:division_long_name::string, '') as conference_name,
    nullif(team:team_logo_url::string, '') as logo_url,
    -- Playoff brackets list a "TBD" team before matchups are set.
    team:code::string = 'TBD' as is_placeholder,
    fetched_at as source_fetched_at
from teams
