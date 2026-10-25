# Style guide

How code in puckmesh is written, so every file reads like the one next to it. Rules come
from official documentation and widely used community guides; where this project departs
from them, the guide says so and why.

| Guide | Covers | Enforced by |
|---|---|---|
| [SQL](sql.md) | Every `.sql` file, plus SQL embedded in Python | [SQLFluff](https://docs.sqlfluff.com/) (`.sqlfluff`) |
| [dbt](dbt.md) | Project layout, model naming, columns, YAML, tests, docs | `dbt parse`, yamllint (`.yamllint.yml`), review |
| [Python](python.md) | `extract/` and any future Python | [Ruff](https://docs.astral.sh/ruff/) (`pyproject.toml`), pytest |
| [Workflow](workflow.md) | Branches, commits, PRs, CI, GitHub Actions | pre-commit, CI, branch protection |

## Principles

These come first. When a rule below seems to conflict with one of them, the principle wins
and the rule gets fixed.

1. **Clarity, then consistency.** dbt Labs' style guide names these as the two tenets of
   code style: write code someone can read quickly, then write all of it the same way.
   Consistency matters more than any single rule: if a file doesn't match the guide, fix
   the file or fix the guide, but don't leave both.
2. **Automate what can be automated.** If a tool can check a rule, the tool checks it,
   in pre-commit and in CI. Human review is for naming, structure, and logic.
3. **Small diffs.** Prefer styles that keep a one-line change a one-line diff (trailing
   commas, no hand-aligned columns).
4. **Comments say why.** Names and types say *what*. Comments explain decisions, source
   quirks, and anything surprising, like the comments on the API's `[]` vs `{}` and the
   unreliable shootout flag. Keep doing that.
5. **One source of truth.** A model's purpose lives in its YAML `description`, a
   setting's default in one module, a magic number in one `var`. Don't restate them
   elsewhere where they can drift.

## Running the checks

```bash
pip install pre-commit sqlfluff ruff yamllint
pre-commit install            # once per clone: checks staged files on every commit
pre-commit run --all-files    # the whole repo, the same checks CI runs
sqlfluff fix transform        # auto-fix SQL layout
ruff format . && ruff check --fix .
```

## Changing the guide

The guide is code: change it in a PR, together with the config and any files that need to
follow the new rule. Record notable decisions in the table below.

### Decisions

| Decision | Chosen | Why | Source |
|---|---|---|---|
| SQL keyword case | lowercase | dbt Labs style; matches the existing models | dbt "How we style our SQL" |
| Aliases in `select` | one space before `as`, no column alignment | Aligned columns turn a one-line change into a block re-indent; dbt's examples don't align | dbt style; principle 3 |
| SQL line length | 100 (dbt Labs uses 80) | VARIANT path + cast expressions don't fit in 80 | — |
| `group by` | `group by all` (dbt prefers `group by 1, 2`) | Can't drift out of sync with the select list; Databricks, Snowflake, DuckDB, and BigQuery support it | — |
| Joins | `on`, never `using` | Explicit, and `using` changes how `select *` and qualified names behave | SQLFluff ST07 |
| Final `select` | Output columns listed in the final `select`, not `select * from final` | Already consistent across the project; keeps the output columns where reviewers look | Deviation from dbt style |
| Key data type | Source integer IDs stay integers in staging | They're integers at the source; cross-league keys still to decide (see dbt guide) | Deviation from dbt style ("keys should be strings") |
| Python formatter | Ruff format (Black-compatible), 88 columns | dbt Labs recommends Black + Ruff; Ruff does both | PEP 8, Ruff docs |
| Docstring style | Google | Readable as plain text; Ruff checks it | Google Python Style Guide §3.8 |
