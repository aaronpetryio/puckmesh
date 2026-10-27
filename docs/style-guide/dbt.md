# dbt style

How the dbt project in `transform/` is laid out and named. Based on dbt Labs'
[How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview),
[How we style our dbt models](https://docs.getdbt.com/best-practices/how-we-style/1-how-we-style-our-dbt-models),
and [Best practices for dbt and Unity Catalog](https://docs.getdbt.com/best-practices/dbt-unity-catalog-best-practices).
SQL layout is in [sql.md](sql.md).

## Layers

```
raw.<league>.<endpoint>         bronze   loaded by extract/, declared as sources, read-only to dbt
  └─ staging/<league>/           silver   stg_<league>__<entity>s, one per source table
       └─ base/                           base_<league>__<entity>s, shared prep for several stg models
  └─ intermediate/               silver   int_<entity>s_<verb>ed, league-agnostic
  └─ marts/                      gold     dim_<entity>s, fct_<grain>s, read by ML and the website
```

| Layer | Allowed | Not allowed | Materialized |
|---|---|---|---|
| **base / staging** | `source()`; rename, cast, clean, categorize; explode VARIANT arrays; pick the latest fetch | Joins to other models, aggregation | view |
| **intermediate** | Joins, unions across leagues, re-graining, isolating hard logic | `source()` | view |
| **marts** | Joins, aggregation, business logic | `source()` | table |

- `source()` appears only in staging and base models (dbt: staging models are "the only
  place we'll use the source macro").
- Staging stays 1:1 with sources. The exception is a source holding several entities, like
  `play_by_play` with nine event types: one `base_` model parses it once, and one `stg_`
  model per entity reads that.
- **Marts read intermediate models once a second league exists.** Until then, marts
  may read `stg_pwhl__*` directly. Once an NCAA source lands, every concept a mart needs
  gets an `int_` model that unions the leagues, and marts stop referencing `stg_`.
  This is the README's "league-agnostic schema" principle.
- **Start as a view; promote when measured.** dbt: "always start with a view ... once
  that view takes too long to practically query, build it into a table, and finally once
  that table takes too long to build ... configure it as an incremental model." A view
  that many models read and that does heavy parsing (`base_pwhl__play_by_play_events`)
  is the first candidate for `+materialized: table`.
- Configure materialization and schema per folder in `dbt_project.yml`. Use an in-model
  `config()` only for the exception.

## Naming

### Models

| Layer | Pattern | Example |
|---|---|---|
| base | `base_<league>__<entity>s` | `base_pwhl__play_by_play_events` |
| staging | `stg_<league>__<entity>s` | `stg_pwhl__shots` |
| intermediate | `int_<entity>s_<verb>ed`, the verb saying what was done (no league: it's cross-league) | `int_shots_enriched` |
| marts, dimension | `dim_<entity>s` | `dim_players` |
| marts, fact | `fct_<grain>s`, named for what one row is | `fct_shots`, `fct_games`, `fct_player_team_seasons` |

- Plural, snake_case, no dots. dbt: "Models should be pluralized."
- Double underscore between league and entity, so the source part is unambiguous.
- Name after the hockey concept, not the API's word: `stg_pwhl__games` (from `schedule`),
  `away` (from `visiting`), `conference` (HockeyTech's "division").

### Columns

| Kind | Rule | Examples |
|---|---|---|
| Primary/foreign key | `<entity>_id`, the same name in every model | `game_id`, `season_id` |
| Key for a role | `<role>_<entity>_id` | `shooter_player_id`, `defending_team_id`, `home_team_id` |
| Boolean | `is_` or `has_` prefix, nothing else | `is_final`, `is_rebound`, `has_overtime` |
| Timestamp | `<event>_at`, UTC | `scheduled_start_at`, `source_fetched_at` |
| Date | `<event>_date` | `game_date`, `birth_date` |
| Measurement | unit suffix | `distance_ft`, `angle_deg`, `height_inches`, `period_seconds` |
| Count | plural noun, no `num_`/`n_` | `goals`, `shot_attempts`, `seasons_on_roster` |
| Categorical | lowercase snake_case values, tested with `accepted_values` | `shot_result in ('on_net', 'goal', 'blocked')` |
| Home/away | `home_` / `away_`, never `visiting_` / `visitor_` | `away_goals` |

- No SQL keywords as names (`result`, `date`): make them specific (`shot_result`,
  `game_date`). SQLFluff RF04 flags these. `position` is the one exception (see
  [sql.md](sql.md#exceptions-in-sqlfluff)).
- No abbreviations a reader has to decode. Hockey-standard ones are fine:
  `xg`, `pp`, `sog` only if spelled out in the column description.
- Every model carries `league_id`.
- **Column order:** keys, then grain columns (season, period, time), then attributes,
  flags, measures, then metadata (`source_fetched_at`) last. Separate groups with blank lines.

### Keys across leagues: still to decide

dbt recommends string keys. Staging keeps the API's integer IDs, which is right for a
single league. They will collide when a second league arrives (PWHL player 123 and NCAA
player 123 are different people), and the README's player crosswalk needs one ID per
person. Decide before the second source lands: either composite keys
`(league_id, player_id)` everywhere, or a string surrogate in intermediate
(`dbt_utils.generate_surrogate_key(['league_id', 'player_id'])`).

## YAML

Per dbt's [How we style our YAML](https://docs.getdbt.com/best-practices/how-we-style/5-how-we-style-our-yaml),
checked by yamllint (`.yamllint.yml`):

- One `_<directory>__models.yml` per folder, plus `_<directory>__sources.yml` in each
  staging folder. Leading underscore so it sorts first. Macros go in `macros/_macros.yml`.
- Two-space indents. List items indented under their key. Lines up to 100; fold long
  descriptions with `>`.
- Use `data_tests:` (not `tests:`) and nest test arguments under `arguments:` (dbt 1.10+).
- Model entries appear in DAG order within a file (base and staging, then int, then marts).

## Documentation

- **Every model has a YAML entry with a `description` whose first sentence states the
  grain:** "One row per shot attempt ...". This is the model's single description.
  Don't repeat it as a comment at the top of the `.sql` file.
- **Mart columns are all documented.** Marts are the contract with the website and the
  ML notebooks. Staging and intermediate columns need a description only when the name
  doesn't say everything (units, null meaning, source quirks).
- Say what null means wherever it isn't obvious ("Null until the game is final").
- Source quirks go in descriptions with evidence, as `stg_pwhl__games` does for the
  schedule's shootout flag ("missed 11 of 29 shootouts").
- Once a mart's columns settle, add a
  [model contract](https://docs.getdbt.com/docs/mesh/govern/model-contracts)
  (`contract: {enforced: true}` with `data_type` per column) so a type or column change
  fails the build instead of breaking the website.

## Tests

- **Every model has a primary key test:** `unique` + `not_null` on the key, or
  `dbt_utils.unique_combination_of_columns` for a composite grain.
- **Every foreign key in a mart has a `relationships` test** to its dimension.
- Every categorical column has `accepted_values`. Every measure with a physical range has
  `dbt_utils.accepted_range`.
- `severity: warn` needs a `description` saying why a failure is tolerable (see
  `shooter_player_id`).
- **Unit tests for logic that parses or calculates**
  ([dbt unit tests](https://docs.getdbt.com/docs/build/unit-tests), dbt 1.8+): height
  parsing, attack-side normalization, distance/angle, decision logic. Data tests check the
  data you have; unit tests check the edge cases you don't have yet.
- Singular tests (`tests/assert_<what_must_be_true>.sql`) for rules that span models,
  like goals reconciling with final scores. They return the failing rows.
- Source freshness: none for now (the README explains why); revisit when the pipeline has
  a heartbeat to check.

## Macros, vars, packages

- A macro needs a reason: logic repeated in three or more models, or a dbt override like
  `generate_schema_name`. Document every macro's purpose and arguments in `_macros.yml`.
- Domain constants are `vars` with a comment giving the source of the number.
- Packages: version range in `packages.yml`, commit `package-lock.yml` (both already done).
- Pin the dbt version in `dbt_project.yml` with `require-dbt-version` to match
  `requirements.txt`.

## Environments

Per dbt's Unity Catalog guidance: bronze is read-only to dbt in every target; developers
write only to `dev` (each to their own `<DBT_SCHEMA>_*` schemas); only the scheduled
pipeline writes to `prod`. Prod should run with its own credential (a service principal,
if Free Edition allows) rather than a personal token.

## Not done yet

- No model contracts on marts (add once their columns settle).
- dbt unit tests cover only shot geometry (`int_shots_enriched`); height parsing and
  decision logic still have none.
- `stg_pwhl__penalty_shots.shot_result_description` is the API's raw text; map it to
  `shot_result` values once the possible values are known.
- Cross-league keys: see "Keys across leagues" above.
