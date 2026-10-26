# CLAUDE.md

Women's hockey analytics (PWHL first): Python extractor → Databricks (raw/bronze) → dbt (silver, gold) → models → static website. See README.md for the stack, phases, and decision log. This file covers how to work in the repo.

## How to work

- **Mistakes mean an instruction gap.** Don't apologize. When something goes wrong, say what in this file (or the README) was missing or unclear, and suggest the fix. If the instruction already existed and was ignored, say that instead. Stay focused on solutions.
- **YAGNI.** Don't overengineer. Build what the task needs, nothing for hypothetical future leagues, models, or scale. Match the engineering to the phase. Right now this is a working pipeline run by one person, not a production platform.
- **Never expand scope without asking.** If you see a worthwhile improvement, suggest it separately; don't fold it into the change. Every change should be easy to justify.
- **Learning project.** The owner is learning data engineering, dbt, and modeling. When you make a non-obvious choice (materialization, join strategy, dedup approach, model choice), explain why in a sentence or two.
- **Ask before:** adding dependencies or tools to the stack, changing gold mart columns/grain, changing the workflow schedule, or anything that touches the `prod` catalog.
- **Proceed without asking on:** fixes and additions inside existing models, extractor endpoints, and tests.
- **Review non-trivial changes.** For changes touching more than one file, or any SQL/model logic, have a subagent on a cheap model review the diff with minimal context before you report done. Fix what it finds, or say why not.

## Hard rules

- **Raw is sacred.** Never edit, delete, or rewrite files in `data/raw/`, the `/Volumes/raw/pwhl/landing/` Volume, or `raw.*` tables. Fix data problems in dbt staging.
- **dbt never writes to `raw`.** Raw tables are dbt sources only, loaded by `python -m extract load`.
- **Dev, not prod.** Run dbt with the default `dev` target. Never use `--target prod` or trigger the GitHub Actions pipeline; the scheduled workflow owns prod.
- **Go easy on the API.** Don't re-fetch from HockeyTech while developing; replay from `data/raw/`. Keep `HockeyTechClient`'s throttle (`min_interval`) in place.
- **Secrets** live in `.env` (template: `.env.example`) and GitHub repo secrets. Never print, log, commit, or hardcode them.
- **Women's leagues only.** Don't add men's league sources.

## Commands

Run dbt from `transform/` (the project-local `profiles.yml` is read from there):

```bash
python -m extract run --mode daily          # fetch changed data, upload, load (what the schedule runs)
python -m extract <endpoint> --all          # seasons | schedule | teams | roster | play-by-play
cd transform
dotenv -f ../.env run -- dbt deps           # first time, or after changing packages.yml
dotenv -f ../.env run -- dbt build --select <model>+   # build a model and everything downstream, with tests
dotenv -f ../.env run -- dbt build          # everything
```

**Verify before saying done.** For dbt changes, `dbt build --select` the changed models plus downstream and report the result. If you can't run it (no `.env` or Databricks access, e.g. in a cloud session), say so plainly. Don't claim it works. Report failures with their output.

## Layout and conventions

- `extract/`: `client.py` (HockeyTech client), `endpoints/` (one module per endpoint: `NAME`, `fetch()`), `raw.py` (save locally, skip unchanged by content hash), `upload.py` → Volume, `load.py` → `COPY INTO`, `pipeline.py` (daily/full runs), `__main__.py` (CLI; add new subcommands here).
- `transform/models/`
  - `staging/<league>/`: `stg_<league>__<entity>`, views in silver. Parse VARIANT, cast, rename, dedupe to the latest fetch. No business logic.
  - `staging/<league>/base/`: shared parsing that several staging models build on (e.g. play-by-play events).
  - `intermediate/`: `int_*`, views in silver. Cross-model logic and enrichment.
  - `marts/`: `dim_*` / `fct_*`, tables in gold. Website- and model-ready.
- Every model gets an entry in its folder's `_*__models.yml` with a description and tests on its grain (`unique`/`not_null`, or `dbt_utils.unique_combination_of_columns`).
- Reconciliation checks go in `transform/tests/assert_*.sql` (return failing rows).
- SQL style: CTEs (`with source as (...)`), `select * from {{ ref() }}` import CTEs at the top, lowercase keywords, aligned `as` aliases, a comment above anything non-obvious. Match the existing models.
- Every model carries `league_id` so leagues can be unioned later.
- Python: plain functions and modules, docstrings on public functions, no frameworks. Match the existing code.
- Commits: short imperative summary of the feature, e.g. "Add play-by-play: extraction, base model, per-event staging".

## Gotchas

- HockeyTech often returns HTTP 200 with an error payload; `parse_body` raises `HockeyTechError`. `statviewfeed` responses are JSONP-wrapped.
- Raw holds one file per *change*, not per fetch. No new rows can just mean nothing changed (e.g. off-season), so there's no source freshness check.
- The schedule's `shootout` flag misses some shootouts. Use `stg_pwhl__shootout_attempts` instead.
- Rink coordinates are HockeyTech's 600×300 grid, not to scale. See `vars` in `dbt_project.yml`.
- Databricks Free Edition: serverless only, a daily fair-usage quota, restricted outbound internet (which is why extraction runs outside Databricks).
