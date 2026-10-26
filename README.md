# Women's Hockey Analytics

Advanced stats, models, and shareable visuals for women's hockey. Starting with the PWHL; expanding to NCAA, international (Worlds), and Olympics.

This is also a learning project: data engineering, analytics engineering (dbt), modeling (xG, ratings, predictions), viz, and product ownership — end to end.

**Scope:** women's leagues only.

---

## Stack

| Layer | Tool | Notes |
|---|---|---|
| Extract | Python (`requests`) | Hits the HockeyTech/LeagueStat API (`client_code=pwhl`). Runs outside Databricks. |
| Raw storage | Unity Catalog Volume (JSON files) | Raw API responses, never edited. Also kept locally for replay. |
| Load | `COPY INTO` (run by the extractor) | Volume files → `raw.<league>.<endpoint>` tables (bronze), incrementally. |
| Warehouse | Databricks Free Edition (Delta, serverless SQL warehouse) | Catalogs: `raw` (bronze), `dev` and `prod` (silver / gold schemas). |
| Transform | dbt Core + `dbt-databricks` | Raw tables are dbt sources; dbt builds silver and gold. |
| Models | Databricks notebooks + MLflow | xG, player ratings, game predictions. |
| Orchestration | Manual → GitHub Actions + Databricks Workflows | Automate only after the pipeline works by hand. |
| Serving | Gold marts exported to Parquet (R2/S3) | Website never queries Databricks live. |
| Website | Next.js or Astro + DuckDB-WASM | Static pages + in-browser SQL for historical search. Daily refresh. |

```
HockeyTech API
   │  Python extractor (laptop → later GitHub Actions)
   ▼
UC Volume: raw JSON files
   │  COPY INTO
   ▼
raw.<league>.<endpoint> tables (bronze, dbt sources)
   │  dbt: silver (staging/intermediate) → gold (marts)
   ▼
Gold Delta tables ──► ML notebooks (xG, ratings, predictions) ──► gold
   │  export
   ▼
Parquet in R2/S3 ──► Website (static pages + DuckDB-WASM search)
```

---

## Running it

**One-time Databricks setup.** dbt creates schemas, but not catalogs or Volumes. Run once in the SQL editor:
```sql
CREATE CATALOG IF NOT EXISTS raw;    -- bronze; written only by the extractor
CREATE CATALOG IF NOT EXISTS dev;    -- your dbt runs: dev.<DBT_SCHEMA>_silver, _gold
CREATE CATALOG IF NOT EXISTS prod;   -- scheduled pipeline only: prod.silver, prod.gold
CREATE SCHEMA  IF NOT EXISTS raw.pwhl;
CREATE VOLUME  IF NOT EXISTS raw.pwhl.landing;
```
The raw tables (`raw.pwhl.seasons`, ...) are created by `python -m extract load`.

**Local setup.** Copy `.env.example` to `.env` and fill it in, then:
```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Scheduled (GitHub Actions).** [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) runs
`python -m extract run` then `dbt build --target prod`:
- **daily** (11:00 UTC): season list; schedule, teams, and rosters for active seasons (a month before
  start to two weeks after end); play-by-play for final games not yet stored, plus the last 3 days' games.
- **full** (Mondays 12:00 UTC): every endpoint for every season and game, to catch corrections and new
  fields in historical data.
- Run either by hand: GitHub → Actions → pipeline → Run workflow.
- Needs repository secrets `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_HTTP_PATH`
  (Settings → Secrets and variables → Actions).

**Change detection.** Each response is hashed (SHA-256 of its JSON, keys sorted, empty `[]`/`{}`
treated alike). The hash goes in the file's `_meta` and in the raw table's `content_hash` column.
Before saving, the extractor reads the latest hash per endpoint/season/team/game from the raw tables
and skips identical responses, so raw holds one file per *change*, not per fetch, on any machine.

**Same steps by hand.**
```powershell
python -m extract run --mode daily     # what the schedule runs: fetch changed data, upload, load
python -m extract seasons              # data/raw/pwhl/seasons/<fetched_at>.json
python -m extract schedule --all       # data/raw/pwhl/schedule/season_id=<n>/<fetched_at>.json
python -m extract teams --all          # data/raw/pwhl/teams/season_id=<n>/...
python -m extract roster --all         # data/raw/pwhl/roster/season_id=<n>/team_id=<n>/...
python -m extract play-by-play --all   # data/raw/pwhl/play_by_play/season_id=<n>/game_id=<n>/... (final games only;
                                       # --new-only skips games already stored, for fast backfill restarts)
python -m extract upload               # copies new files to /Volumes/raw/pwhl/landing/
python -m extract load                 # COPY INTO raw.pwhl.<endpoint> (only new files)
cd transform
dotenv -f ../.env run -- dbt deps      # first time, or after changing packages.yml
dotenv -f ../.env run -- dbt build     # sources → staging, plus tests
```

---

## Phases

**Phase 0 — Hello world (start here)**
Everything runs from a laptop. No scheduling, no website.
1. Create a catalog/schema and a Volume in Databricks Free Edition. Create a personal access token.
2. `extract.py`: pull one endpoint (seasons, then schedule), strip the JSONP wrapper, save JSON locally, upload to the Volume with `databricks-sdk`.
3. `dbt init` with `dbt-databricks`, pointed at the serverless SQL warehouse.
4. `COPY INTO raw.pwhl.schedule`, declared as a dbt source → `stg_pwhl__games` → tests (`unique`, `not_null` on `game_id`).
5. `dbt build` from the laptop. Done when games show up as a typed, tested table.

**Phase 1 — Full PWHL backfill**
All seasons since the inaugural one (season_id=1). Endpoints: schedule, standings, rosters, skater/goalie stats, play-by-play (needed for xG). Core marts: `dim_players`, `dim_teams`, `fct_games`, `fct_shots`, `fct_player_game`.

**Phase 2 — Daily automation**
GitHub Actions cron (morning after games) runs the extractor, uploads to the Volume, then triggers a Databricks Workflow: `dbt build` (dbt task) → scoring notebooks → Parquet export.

**Phase 3 — Models**
xG from shot-level play-by-play, then player ratings, then game predictions. Tracked in MLflow; outputs written back as gold tables.

**Phase 4 — Website**
Player pages, game pages, shareable cards (pre-rendered OG images), historical search via DuckDB-WASM over exported Parquet.

**Phase 5 — More leagues**
NCAA women's, Worlds, Olympics. Likely different sources and scrapers; only the extract and staging layers should care.

---

## Design principles (stay pivot-friendly)

- **Extraction lives outside Databricks.** Free Edition restricts outbound internet, and keeping the extractor separate means the warehouse is swappable.
- **Raw is sacred.** Store every API response as-is, with `league`, `season_id`, `endpoint`, `fetched_at`. Any layer can be rebuilt from raw without re-hitting the API.
- **One dbt target at a time.** Databricks now. Swapping to Snowflake, DuckDB, or Postgres means changing the adapter and fixing staging-layer SQL, not rewriting the project.
- **The website reads files, not the warehouse.** Hosting cost stays near zero, and the warehouse can change without touching the site.
- **League-agnostic schema.** Per-league staging models (`stg_pwhl__*`, `stg_ncaa__*`) union into canonical intermediate models with a `league_id`.
- **One player, one ID.** A player crosswalk (`dim_players` + xref seed) links the same person across NCAA → PWHL → international.
- **Automate last.** Get it working by hand, then schedule it.

---

## Repo layout

```
.
├── extract/               # Python: API client, endpoints, upload to Volume
│   ├── client.py          # league-parameterized HockeyTech client
│   ├── endpoints/
│   ├── raw.py             # save responses locally (skips unchanged, by content hash)
│   ├── state.py           # latest stored hash per endpoint/partition, read from raw tables
│   ├── upload.py          # local files → Volume
│   ├── load.py            # Volume → raw tables (COPY INTO)
│   └── pipeline.py        # daily / full scheduled runs
├── data/raw/              # local copy of raw JSON (gitignored)
├── transform/             # dbt project
│   └── models/
│       ├── staging/       # sources + stg_<league>__<entity>
│       ├── intermediate/  # cross-league canonical models
│       └── marts/         # dim_*, fct_*, website-ready tables
├── ml/                    # Databricks notebooks: xG, ratings, predictions
├── export/                # gold → Parquet for the website
├── app/                   # website (later)
└── .github/workflows/     # pipeline.yml (scheduled runs), ci.yml (pull request checks)
```

---

## Known constraints

- Databricks Free Edition: serverless only, outbound internet restricted to trusted domains, max 5 concurrent job tasks, a fair-usage quota that can shut compute off for the day, non-commercial use only, and inactive accounts can be deleted.
- To verify: Free Edition support for the dbt task type in Workflows (fallback: a Python task that runs dbt).
- The HockeyTech Firebase endpoint (live game data) seems unavailable out of season. Historical endpoints work.

---

## Differentiation (vs. existing PWHL analytics)

An existing site already covers xG, GSAx, shot maps, and player cards. Focus elsewhere:
- Composite player ratings
- Game predictions with tracked accuracy
- Multi-league coverage with linked player histories
- Shareable, social-ready player and game cards
- Open methodology

---

## Decision log

| Decision | Why | Revisit if |
|---|---|---|
| Databricks as warehouse | Primary learning goal | Free Edition limits block progress |
| dbt Core, run by Databricks Workflows | One DAG for ingest → dbt → ML → export | Want dbt Cloud experience |
| Extract outside Databricks | Free Edition network limits; portability | — |
| Static site + Parquet + DuckDB-WASM | Daily refresh, near-zero cost, browser search | Need live in-game updates |
| No Airflow / Fivetran / Snowflake yet | Overkill or wrong fit for now | Phase 2+ learning goals |

---

## References

- [PWHL-Data-Reference](https://github.com/IsabelleLefebvre97/PWHL-Data-Reference): HockeyTech + Firebase endpoint documentation
- [PWHLByTheNumbers](https://github.com/msaunders804/PWHLByTheNumbers): similar pipeline (raw JSON cache approach)
- [pwhl.hockey-statistics.com](https://pwhl.hockey-statistics.com/): existing PWHL analytics site
