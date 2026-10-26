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

- Name the grouped columns: `group by game_id, shooting_team_id`. Not `group by 1, 2`
  and not `group by all`, so the grain is readable right where it's set. (Deviation:
  dbt prefers numbers, to avoid repeating the select list.) SQLFluff AM06 catches
  numbers; a pre-commit check catches `all`.
- Group by a column, not a long expression. If you need to group by a computed value,
  compute it in an earlier CTE and group by its name.
- `order by` follows the same rule: names, not positions.
- Plain columns before aggregates and window functions in the select list.
- Aggregate before joining, on the smallest data you can.
- `order by` in a window gives every column a direction or none of them:
  `order by start_date desc, team_id asc`.
- Deduplicate with `qualify row_number() over (...) = 1`, and say in a comment what the
  tiebreaker is for if there is one (see `dim_players`).

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
| Keys we write (`_meta.season_id`) and keys of the schedule, team, and roster lists | strict: `game:game_id::int` | Fails loudly if the API changes, and the build stops instead of loading nulls |
| Play-by-play event fields, including IDs, and optional or messy attributes (`attendance`, `goalie_id`, coordinates) | lenient: `try_cast(event:goalie_id::string as int)` | Event fields arrive as strings and can be blank; a null is caught by a test instead of failing the build |
| Optional strings | `nullif(team:city::string, '')` | Blank becomes null |
| 0/1 flags | `event:home::int = 1` | Null when the field is missing; `coalesce(..., false)` if false is right |

`try_cast` already returns null for `''`, so `try_cast(nullif(x::string, '') as int)` is
the same as `try_cast(x::string as int)`. Use the shorter one.

Every `try_cast` is a decision to accept bad data quietly. When it guards something
downstream logic depends on, back it with a `not_null` or `accepted_range` test, as the
event models do for `shooter_player_id`, `scoring_team_id`, and the other IDs they need.

### Casting style

`::` for casts (`::int`, `::timestamp`); `try_cast(... as type)` when a failed cast
should give null. Don't mix `cast(x as int)` in.

### Dialect-specific functions

`qualify`, `count_if`, `min_by`/`max_by`, and `ignore nulls` are fine to
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
  constants or trusted config, always backtick-quoted (`db.raw_table()`), and mark the
  statement `# noqa: S608` with a comment saying why, so the exception is visible.

## Exceptions in `.sqlfluff`

- `structure.column_order` is off: it fights dbt's "group columns by type" ordering.
- `ambiguous.column_count` is off: it flags `select located.*`, which intermediate models
  use on purpose to carry every staging column through.
- `position` is allowed as a column name: it's the hockey term and isn't reserved in
  Databricks SQL.
