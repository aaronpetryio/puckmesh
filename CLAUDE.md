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
python -m extract seasons                   # the season list
python -m extract <endpoint> --all          # schedule | teams | roster | play-by-play (or --season <id>)
python -m ml.xg score                       # score the current season with the registered xG model (dev)
python -m ml.xg train --through-season 2026 # once a season ends: backfill xG, register a new model (dev)
cd transform
dotenv -f ../.env run -- dbt deps           # first time, or after changing packages.yml
dotenv -f ../.env run -- dbt build --select <model>+   # build a model and everything downstream, with tests
dotenv -f ../.env run -- dbt build          # everything
```

Checks that need no warehouse, from the repo root:

```bash
pip install -r requirements.txt -r requirements-ml.txt -r requirements-dev.txt   # once, e.g. in a fresh cloud container
git add <new files>                         # pre-commit --all-files only checks tracked files
pre-commit run --all-files                  # ruff, sqlfluff, yamllint, ... (CI's lint job)
python -m pytest                            # extract/ and ml/ unit tests
```

xG notebooks run in Databricks, by hand: clone the repo as a Git folder in the workspace, open `notebooks/xg_baselines`, check the schema widgets, Run all.

**Verify before saying done.** Run the checks above. For dbt changes, also `dbt build --select` the changed models plus downstream and report the result. If you can't run it (no `.env` or Databricks access, e.g. in a cloud session), say so plainly. Don't claim it works. Report failures with their output.

In a cloud session without Databricks access, push the branch and open the PR: CI's `dbt` job runs the full `dbt build` against `dev.ci_*`. Read its result before reporting done.

## Layout and conventions

Style rules (naming, SQL layout, YAML, tests, Python) are in `docs/style-guide/`, and the linters enforce most of them. When this file and the guide disagree, the guide wins; fix this file. The points below are the ones that come up most.

- `extract/`: `client.py` (HockeyTech client), `endpoints/` (one module per endpoint: `NAME`, `fetch()`, and helpers that read its response; only that module knows the response's shape), `raw.py` (save locally, skip unchanged by content hash), `upload.py` → Volume, `load.py` → `COPY INTO`, `db.py` (warehouse connection and settings; read environment variables here, not elsewhere), `pipeline.py` (daily/full runs), `__main__.py` (CLI; add new subcommands here). Tests in `tests/`.
- `ml/xg/`: expected-goals model code as plain modules (`data.py` training set and folds, `model.py`, `metrics.py`, `evaluate.py`, `publish.py` predictions-table SQL), unit-tested in `tests/`. No plotting, and no warehouse or MLflow access except in `__main__.py`, the `python -m ml.xg` command that trains, registers and scores (the prod model is trained only by the manual `train.yml` workflow). Dependencies in `requirements-ml.txt`; scikit-learn is pinned exactly, and bumping it means retraining.
- `notebooks/`: Databricks notebooks in source format (`.py`), for exploring and comparing models by hand. They call `ml/xg/` and draw charts; never part of the scheduled pipeline.
- `transform/models/`
  - `staging/<league>/`: `stg_<league>__<entity>s`, views in silver. Parse VARIANT, cast, rename, dedupe to the latest fetch. No joins, aggregation, or business logic.
  - `staging/<league>/base/`: shared parsing that several staging models build on (e.g. play-by-play events).
  - `intermediate/`: `int_<entity>s_<verb>ed` (e.g. `int_shots_enriched`), views in silver. Cross-model logic and enrichment.
  - `marts/`: `dim_<entity>s` / `fct_<grain>s` (plural, named for what one row is), tables in gold. Website- and model-ready.
- Every model gets an entry in its folder's `_*__models.yml` with a description stating its grain and tests on that grain (`unique`/`not_null`, or `dbt_utils.unique_combination_of_columns`). Every mart column gets a description.
- Reconciliation checks go in `transform/tests/assert_*.sql` (return failing rows).
- SQL: import CTEs at the top for every `ref()`, lowercase keywords, one space before `as` (no aligned aliases), `on` joins, `group by` column names. A comment above anything non-obvious; the model's purpose goes in its YAML description, not a header comment. Constants with domain meaning are `vars` in `dbt_project.yml`.
- Booleans start with `is_` or `has_`; timestamps end in `_at`, dates in `_date`.
- Every model carries `league_id` so leagues can be unioned later.
- Python: plain functions and modules, no frameworks. Type hints on public functions; a docstring on every module, and on functions whose name and types don't say enough. `logging` in library modules, `print` only in `__main__.py`.
- Commits: short imperative summary of the feature, e.g. "Add play-by-play: extraction, base model, per-event staging".
