# SQL style

Applies to every `.sql` file in `transform/` and, by review, to SQL embedded in Python
(`extract/load.py`, `extract/state.py`). Based on dbt Labs'
[How we style our SQL](https://docs.getdbt.com/best-practices/how-we-style/2-how-we-style-our-sql)
and their [SQLFluff config](https://github.com/dbt-labs/jaffle-shop/blob/main/.sqlfluff),
adapted for Databricks SQL. `.sqlfluff` enforces the layout rules; run `sqlfluff fix transform`.

## Layout

- Lowercase keywords, functions, and identifiers: `select`, `count_if`, `qualify`.
- Four-space indents. Lines up to 100 characters.
- Trailing commas.
- `as` written explicitly for every column and table alias.
- One space before `as`. Don't pad aliases into a column: realigning a block for one long
  name makes the diff hide the real change.
- One select target per line, unless there's only one.
- Blank lines separate groups of columns (keys, attributes, flags, metadata), as the
  staging models already do.

```sql
-- yes
select
    game_id,
    try_cast(event:team_id::string as int) as scoring_team_id,
    event:home::int = 1 as is_home_team,

    source_fetched_at
from events

-- no
select game_id, try_cast(event:team_id::string as int)  as scoring_team_id,
    event:home::int = 1                                    as is_home_team
```

## CTEs

- **Import CTEs at the top.** Every `{{ ref() }}` / `{{ source() }}` goes in a CTE named
  after the model it reads (`games`, `shots`), not inline in a later `join`.
  Select only the columns you use, filtered as early as possible (dbt: "Limit the data
  scanned by CTEs as much as possible").
- **Functional CTEs do one thing**, and their names say what: `latest_fetch`,
  `attack_side`, `score_state`. Avoid names that don't describe the step (`renamed`
  for a CTE that parses height, `final`, `cte1`).
- A CTE repeated across models becomes its own model (dbt's rule) or a macro.

## Joins

- Write the join type: `inner join`, `left join`. Never bare `join`, never `right join`
  (swap the tables instead).
- `on`, not `using`.
- In join conditions, list the table introduced earlier first:
  `on shots.game_id = games.game_id`, not `on games.game_id = shots.game_id`.
- With more than one table in scope, qualify every column (`located.game_seconds`).
- Alias tables with real words (`home`, `away`, `home_shots`), never initialisms
  (`g`, `h`, `a`, `s`). dbt: "it's harder to understand what the table called 'c' is as
  compared to 'customers'."
- `union all` unless you mean to remove duplicates.

## Grouping, ordering, windows

- `group by all`. (dbt prefers `group by 1, 2`; `all` has the same benefit, not
  repeating the select list, and can't fall out of sync with it.)
- Plain columns before aggregates and window functions in the select list.
- Aggregate before joining, on the smallest data you can.
- `order by` in a window gives every column a direction or none of them:
  `order by start_date desc, team_id asc`.
- Deduplicate with `qualify row_number() over (...) = 1`, and say in a comment what the
  tiebreaker is for if there is one (see `dim_player`).

## Comparisons and nulls

- `!=`, not `<>`.
- Remember that `!=` and `not` drop nulls: `where shot_result != 'blocked'` excludes
  rows where `shot_result` is null. Say so in a comment if that's intended and not obvious.
- `coalesce` for defaults; `nullif(x, '')` to turn blank strings into nulls.

## Databricks specifics

### Reading VARIANT

Raw tables store whole API responses as `VARIANT`. Extract with path syntax and cast with
`::`. How you cast depends on whether the field must be there:

| Field | Cast | Why |
|---|---|---|
| Keys and fields the model depends on (`game_id`, `season_id`, `home_team`) | strict: `game:game_id::int` | Fails loudly if the API changes, and the build stops instead of loading nulls |
| Optional or messy attributes (`attendance`, `goalie_id`, coordinates) | lenient: `try_cast(event:goalie_id::string as int)` | Blank or odd values become null |
| Optional strings | `nullif(team:city::string, '')` | Blank becomes null |
| 0/1 flags | `event:home::int = 1` | Null when the field is missing; `coalesce(..., false)` if false is right |

`try_cast` already returns null for `''`, so `try_cast(nullif(x::string, '') as int)` is
the same as `try_cast(x::string as int)`. Use the shorter one.

Every `try_cast` is a decision to accept bad data quietly. When it guards something
downstream logic depends on, back it with a `not_null` or `accepted_range` test.

### Casting style

`::` for casts (`::int`, `::timestamp`); `try_cast(... as type)` when a failed cast
should give null. Don't mix `cast(x as int)` in.

### Dialect-specific functions

`qualify`, `count_if`, `min_by`/`max_by`, `group by all`, and `ignore nulls` are fine to
use everywhere. VARIANT paths (`:`), `variant_explode`, and `try_variant_get` belong only
in staging and base models, which keeps the README's "swap the warehouse by rewriting
staging" promise.

## Comments

- `--` for comments about the SQL. `{# #}` for comments in Jinja blocks and macros, and
  for anything that shouldn't appear in compiled SQL.
- Don't restate the model's description at the top of the file; that lives in YAML
  (see [dbt guide](dbt.md#documentation)). Comment the non-obvious steps.

## Magic numbers

A constant with domain meaning (rink dimensions, period length, the rebound window) is a
`var` in `dbt_project.yml` with a comment saying where the number comes from. Literal
`600`, `300`, `1200`, and `3` in a model mean the next reader has to work out what they are.

## SQL in Python

Same rules (lowercase, layout, qualification). Also:

- **Values are bound, never formatted in.** `databricks-sql-connector` (3.0+) supports
  named parameters: `cur.execute("select ... where source_file = :f", {"f": path})`.
- **Identifiers** (catalog, schema, table) can't be bound. Only interpolate them from code
  constants or trusted config, always backtick-quoted, and mark the line
  `# noqa: S608 - identifiers only, from config` so the exception is visible.

## Where main doesn't follow this yet

From `sqlfluff lint transform` on main: 20 of 21 files fail, almost all on layout that
`sqlfluff fix` corrects. These need a person:

- `using` joins: `dim_player`, `dim_team`, `fct_games`, `fct_player_team_seasons`, `fct_shots`.
- Inline `ref()`s in joins: `fct_games` (seasons), `fct_shots`, `fct_player_team_seasons`.
- Initialism aliases: `tests/assert_pwhl_goals_match_final_score.sql` (`g`, `h`, `a`, `s`).
- Unqualified columns with two tables in scope: `int_shots_enriched` (final select).
- Join condition order: `int_shots_enriched`, `fct_games`.
- Redundant `nullif` inside integer `try_cast`: 14 places in staging.
- Strict vs lenient casts don't follow the table above: event models `try_cast` their keys
  (`team_id`, `player_id`) while `stg_pwhl__games` casts keys strictly.
- Literal `600` / `300` in `int_shots_enriched` next to `rink_*` vars; `1200` in the base model.
- Embedded SQL in `extract/` is uppercase; `extract/load.py` formats values into a `MERGE`.
