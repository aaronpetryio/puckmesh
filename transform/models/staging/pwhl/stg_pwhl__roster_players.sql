with source as (
    select
        payload:_meta.season_id::int        as season_id,
        payload:_meta.team_id::int          as team_id,
        payload:_meta.fetched_at::timestamp as fetched_at,
        payload:response                    as response
    from {{ source('pwhl', 'roster') }}
),

latest_fetch as (
    select *
    from source
    qualify row_number() over (partition by season_id, team_id order by fetched_at desc) = 1
),

entries as (
    select
        latest_fetch.season_id,
        latest_fetch.team_id,
        latest_fetch.fetched_at,
        r.value as player
    from latest_fetch,
        lateral variant_explode(latest_fetch.response:SiteKit.Roster) as r
),

players as (
    -- The Roster array also holds the coaching staff as a nested list, and is
    -- empty before a season's rosters are published. Only players have player_id.
    select *
    from entries
    where player:player_id is not null
),

renamed as (
    select
        season_id,
        team_id,
        fetched_at,
        player,
        nullif(player:height::string, '') as height_raw
    from players
)

-- One row per player per team per season. A player traded mid-season has a row on each team.
select
    'pwhl'                                              as league_id,
    player:player_id::int                               as player_id,
    try_cast(player:person_id::string as int)           as person_id,
    season_id,
    team_id,

    player:first_name::string                           as first_name,
    player:last_name::string                            as last_name,
    player:name::string                                 as full_name,
    try_cast(player:tp_jersey_number::string as int)    as jersey_number,

    player:position::string                             as position,
    case
        when player:position::string = 'G' then 'G'
        when player:position::string in ('D', 'LD', 'RD') then 'D'
        else 'F'
    end                                                 as position_group,
    nullif(player:shoots::string, '')                   as shoots,

    try_cast(player:birthdate::string as date)          as birthdate,
    nullif(player:birthtown::string, '')                as birth_city,
    nullif(player:birthprov::string, '')                as birth_region,
    nullif(player:birthcntry::string, '')               as birth_country,
    nullif(player:hometown::string, '')                 as hometown,

    -- Height arrives as 5'7, 5'7", 5'7'', 5.07, ...: first digit is feet, next one or two are inches.
    -- Weight is not used: the API returns 0 or blank for every player.
    case
        when regexp_extract(height_raw, '^([0-9])[^0-9]+([0-9]{1,2})', 1) != ''
            then cast(regexp_extract(height_raw, '^([0-9])[^0-9]+([0-9]{1,2})', 1) as int) * 12
               + cast(regexp_extract(height_raw, '^([0-9])[^0-9]+([0-9]{1,2})', 2) as int)
    end                                                 as height_inches,

    player:rookie::int = 1                              as is_rookie,
    nullif(nullif(player:status::string, ''), 'None')   as roster_status,
    player:active::int = 1                              as is_active,
    nullif(player:player_image::string, '')             as headshot_url,

    fetched_at                                          as source_fetched_at
from renamed
