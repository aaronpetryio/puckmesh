with source as (
    select * from {{ source('ml', 'xg_predictions') }}
)

select
    league_id,
    game_id,
    event_index,
    season_year,
    model_version,
    xg_raw,
    xg,
    scored_at
from source
where model_version = '{{ var("xg_model_version") }}'
