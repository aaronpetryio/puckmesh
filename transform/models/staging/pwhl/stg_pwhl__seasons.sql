with source as (
    select
        payload:_meta.fetched_at::timestamp as fetched_at,
        payload:response                    as response
    from {{ source('pwhl', 'seasons') }}
),

latest_fetch as (
    select *
    from source
    qualify row_number() over (order by fetched_at desc) = 1
),

seasons as (
    select s.value as season
    from latest_fetch,
        lateral variant_explode(latest_fetch.response:SiteKit.Seasons) as s
)

select
    'pwhl'                                    as league_id,
    season:season_id::int                     as season_id,
    season:season_name::string                as season_name,
    season:shortname::string                  as season_short_name,
    case
        when season:playoff::int = 1 then 'playoffs'
        when season:season_name::string ilike '%pre%season%' then 'preseason'
        else 'regular'
    end                                       as season_type,
    season:career::int = 1                    as counts_toward_career,
    try_cast(season:start_date::string as date) as start_date,
    try_cast(season:end_date::string as date)   as end_date
from seasons
