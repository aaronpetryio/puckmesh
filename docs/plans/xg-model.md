# Plan: xG model for the PWHL (shots on goal only)

Status: step 1 (audit) done, follow-ups pending; see [Decisions](#decisions).

## Prior PWHL xG work

| Who | Data | Shots used | Features | Model | Notes |
|---|---|---|---|---|---|
| 18 Skaters, "Simple PWHL xG Model" (May 2024) [1] | PWHL/HockeyTech API, 72 games | Shots on goal | Distance, angle, rebound | MARS (regression splines) | Few features because of the small sample. Notes anomalies and errors in the API data. |
| sportsdataverse `pwhl_shot_xg` [2][3][4] | HockeyTech play-by-play | On-net shots only ("No missed shots in the feed") | Not documented | Logistic regression | Replaced NHL models, which predicted only 66–74% of actual PWHL goals. Backtests use a prior-season model. |
| Draft Chalkboard [5] | 11,625 shots, two seasons | Unclear | Not shown | Not shown | Uses shift charts for on-ice 5v5 work. |
| Corsi Chronicles [6] | InStat play-by-play (proprietary) | 7,249 shots, 602 goals | Rebounds, rushes, cycles, tips, goalie movement, power play | Logistic regression | Reports AUC 0.944. Not comparable to ours: InStat has context we don't, and 0.944 is far above the ~0.75–0.80 typical of public NHL models. |
| Sameelytics, GSAx [7] | PWHL shots | — | Distance/angle regions | Weighted zones, no fitted model | Says there isn't enough data to fit a model on x/y alone. |
| The Ice Garden [8] | PWHL shot tracker | — | Danger zones | None | The tracker records only the shot's original location, so tips and deflections aren't visible. |
| pwhl.hockey-statistics.com [9] | — | — | — | — | Existing site with xG (see README "Differentiation"). Method not reviewed: the site wasn't reachable. |

### What this means for us

1. **Our setup is the PWHL norm.** Every public HockeyTech-based model is effectively P(goal | shot on goal). Our numbers won't be comparable to NHL xG, which also counts missed shots.
2. **Simple models are what has worked.** With roughly 15–20k shots on goal across all seasons (to be checked in step 1), a regularized logistic model will probably match gradient boosting and is easier to explain.
3. **The coordinates are rough.** Every source mentions noise, and `dbt_project.yml` already says the grid is "not drawn to scale". Validate the scale before distance becomes the main feature.

## What losing missed shots costs, and what it doesn't

- **Calibration still works.** Every goal is a shot on goal, so total xG should still add up to total goals.
- **GSAx is barely affected.** Goalies only face shots on goal anyway.
- **Shooters who miss the net a lot look better than they are,** and that leaks into team xGF. State this on the site rather than modeling around it.
- **Name it honestly,** e.g. "xG (shots on goal)", and don't compare rates to NHL models. The goal rate per shot on goal is higher than an NHL model's rate per unblocked attempt [12][13].

## Steps

### 1. Data audit

Queries, results, and findings: [xg-audit.md](xg-audit.md).

- **The audit's answers:**
  - 18,022 shots at a goalie and 1,476 goals in the regular season and playoffs; preseason is left out of training.
  - Goals reconcile exactly, and no shot is missing coordinates.
  - Tips are recorded. "Default" (unknown) is a third of shot types.
  - `is_quality_chance` is a location zone, not leakage: a benchmark, not a feature.
  - Empty nets look undercounted (9 shots in three seasons), which follow-up 5a checks.

What the audit looked at:

- Shots and goals per season, and the overall goal rate.
- How many distinct shot types there are, and whether tips and deflections are recorded.
- **Whether `is_quality_chance` gives away the outcome.** `stg_pwhl__shots` detects goals by matching "goal" in `shot_quality_description`. If the league sets the flag after the result is known, it can't be a feature. Use it as a benchmark instead.
- Missing coordinates, and empty-net shots.
- Dropped: whether blocked-shot coordinates are the shooter's position or the blocker's. Blocked shots aren't in the training set.

Already known:

- **Rink scale: done.** `fct_shots` has `x_ft` / `y_ft` / `distance_ft` / `angle_deg` on the fastRhockey convention; see [rink-coordinates.md](rink-coordinates.md).
- **Shots on goal only.** HockeyTech records no missed shots.
- **Coordinates are noisy.**
  - About 1.8% of shots at a goalie (353 of 19,376) sit on the wrong half for their team's period, and they convert at 10.5%. These are scorer placement errors.
  - About 1.5% of game-periods have the ends swapped.
  - Shots from 70–89 ft convert at ~3%.
  - The model has to tolerate this noise.
- **No strength state on shots.** It has to be rebuilt from penalties and goalie changes (step 2).

### 2. Features in dbt, not Python

- Already available: `distance_ft`, `angle_deg`, `shot_type`, `is_rebound`, `seconds_since_team_prev_shot`, `score_diff`, `period`, `is_home_team`.
- **Strength state (5v5, power play, shorthanded) is missing.** It's the biggest gap. Today only goals carry power-play flags. It would come from a new intermediate model that rebuilds man-advantage from penalties: duration, minors ending early on a power-play goal, offsetting penalties, and goalie pulls from `stg_pwhl__goalie_changes`. Its own PR, with a reconciliation test checking power-play goals against the goals' `is_power_play` flag.
  - **How others do it:**
    - fastRhockey, and sportsdataverse's older path, use simple windows. Each penalty the league marks as a power play (`pp`) opens a window of its length, closed by the next goal of any kind. There's no 5v3 or skater count.
    - sportsdataverse's newer path counts skaters from HockeyTech's shift feed (`modulekit` / `gameshifts`), which we don't fetch. In 2025, 5–8% of its events had implausible counts, and it has no counts for 2024 or 2025 shots.
    - We take the penalty rebuild, which is more careful than the windows. Shifts stay a fallback if the reconciliation fails.
  - **Edge cases to handle:**
    - Which penalties change strength: use the league's `pp` flag on the penalty, which should already exclude coincidental penalties.
    - Misconducts (10 min) and game misconducts take no one off the ice.
    - A penalty shot replaces the power play.
    - Double minors (4 min): a power-play goal ends only the current 2 minutes.
    - Majors and match penalties: run the full 5 minutes whatever happens.
    - Two in the box at most: a third penalty waits until the first one ends, so a team never drops below 3 skaters.
    - On a 5v3 goal, only the penalty that started first ends.
    - Short-handed goals end nothing.
    - Penalties carry across period breaks; `game_seconds` already runs on through the game.
    - Regular-season overtime is 3-on-3, so a penalty adds a skater for the other team (4v3) instead of removing one. Playoff overtime is 5-on-5. Query 5c checks this.
    - Same-second order: a shot and a penalty in the same second follow `event_index`, not the clock.
    - Pulled goalies: from `stg_pwhl__goalie_changes`, the team with an empty net counts as 6 skaters. Delayed-penalty pulls probably aren't recorded; that's a known gap.
  - **Tests:**
    - Goals' `is_power_play` / `is_short_handed` flags.
    - The on-ice player lists on each goal, if query 5c shows they're complete. They give real skater counts at every goal.
- Maybe a rough rush flag (a shot within a few seconds of an event in another zone), if step 1 shows the event timing supports it.
- Why the features go in dbt: they get tested and documented there, and the ratings and predictions models can reuse them. The Python side reads one table.

### 3. Training set and baselines

- Train on unblocked, non-empty-net shots in regulation and overtime. Leave out shootouts and penalty shots, which are already separate event types.
- Baselines to beat: league-average goal rate, then distance only, then distance + angle (roughly the 18 Skaters model [1]).

### 4. Model v1

- Logistic regression with splines on distance and angle, plus shot type, rebound, and strength state.
- One comparison with gradient boosting (LightGBM or XGBoost) [10]. Keep it only if it clearly beats logistic on held-out data.
- Empty-net shots get their own model or a fixed value, as Evolving-Hockey and Hockey Alchemy do [10][11].

### 5. Evaluation

- **Split by season, not by random shot.** Train on earlier seasons and test on the next, so a shot and its rebound never sit on both sides of the split. This mirrors how the model is used.
- **Metrics:** log loss and Brier score first, since xG is a probability. Then calibration plots by distance band and season, and AUC last. Always compare against the baselines.
- **Sanity checks:** total xG vs goals per season, the top shooters and goalies by xG, and strength-state goal rates.
- Skill-related bias in pooled xG models is a known issue [13]. Note it; don't solve it in v1.

### 6. Write back and use the predictions

- Each season is scored by a model that never saw it: out-of-fold for past seasons, the prior-season model for the current one [2]. This keeps in-sample overfitting out of the published numbers.
- Predictions go in their own table keyed on `game_id, event_index`, with `model_version`. Declare it as a dbt source, and build player xG, team xG, and GSAx marts on it in dbt.
- Track runs in MLflow, which is included in Databricks Free Edition.

### 7. Automate (later)

Add a scoring step to the daily workflow after dbt. This changes the schedule, so it needs separate approval.

### Where it lives

`ml/xg/` holds plain Python modules for features, training, scoring, and evaluation. Notebooks are only for exploring the audit and plots. Tests go in `tests/`.

## Decisions

These are "ask before" items in CLAUDE.md.

1. **New dependencies (open):**
   - Proposed: `requirements-ml.txt` with scikit-learn, pandas, and mlflow, installed together with `requirements.txt` only in the jobs that need them.
   - No LightGBM or XGBoost unless a test shows logistic regression falls short.
2. **Strength state (agreed in principle):**
   - The logic goes in a new intermediate model.
   - `fct_shots` gains `skaters_for`, `skaters_against`, and `strength_state` (e.g. `5v4`).
   - Edge cases are listed under step 2. Final sign-off on the columns is still needed.
3. **Predictions table (decided):**
   - One row per shot per model version, keyed on `game_id, event_index, model_version`.
   - Written by Python to a new `ml` schema (`dev.ml.xg_predictions`, later `prod.ml.xg_predictions`) and declared as a dbt source.
   - Creating the prod schema gets asked about again when we reach that step.
4. **Daily scoring (decided: yes, after model v1):**
   - The daily run scores new shots with the saved model, so yesterday's games get xG the next morning.
   - Order: extract → dbt build → score → dbt build of the xG marts.
   - Training stays manual: when the model changes, or once a season.

## Positioning

The README says an existing site already covers xG, so this project focuses on ratings, predictions, and open methodology. xG here is a building block, and the bar for v1 is "well calibrated, simple, and documented in the open".

## Caveats

- Most sources were not read in full. Sources [1] and [5]–[9] failed DNS from the cloud session that wrote this plan, so their details come from search-result summaries. Check them before citing them on the site.
- The sample size is an estimate until step 1 runs.

## Sources

PWHL-specific:

1. 18 Skaters, "Simple PWHL xG Model" (May 2024): <https://www.18skaters.com/2024/05/simple-pwhl-xg-model_13.html>. Not read in full (search summary only).
2. sportsdataverse-py PR #846, `pwhl_shot_xg` on on-net shots, prior-season backtests: <https://github.com/sportsdataverse/sportsdataverse-py/pull/846>. Read directly.
3. sportsdataverse-py PR #729, empty-net goals measured to the attacking net: <https://github.com/sportsdataverse/sportsdataverse-py/pull/729>. Search summary only.
4. fastRhockey, R package for PWHL data, incl. `load_pwhl_xg_pbp()`: <https://github.com/sportsdataverse/fastRhockey>; Corsi/Fenwick proxies with no missed shots in the feed: <https://rdrr.io/cran/fastRhockey/man/pwhl_game_corsi.html>. README read directly; the Corsi page from search summary only.
5. Draft Chalkboard, "Measuring What Defenders Actually Do": <https://draftchalkboard.com/hockey/articles/pwhl-defensive-impact>. Search summary only.
6. Corsi Chronicles, "PWHL analytics": <https://corsichronicles.substack.com/p/pwhl-analytics>. Search summary only.
7. Sameelytics, "Using PWHL Shot Data to measure Goals Saved Above Expected": <https://sameelytics.substack.com/p/using-pwhl-shot-data-to-measure-goals>. Search summary only.
8. The Ice Garden, "PWHL Boston shot quality analysis, first five games": <https://www.theixsports.com/the-ice-garden/analytics/pwhl-boston-shot-quality-analysis-first-five-games/>. Search summary only.
9. pwhl.hockey-statistics.com: <https://pwhl.hockey-statistics.com/>. Not reachable.

Also seen, not used above:

- The Hockey News, "Advanced 2026 PWHL Drafting: Expected Goals": <https://thehockeynews.com/womens/pwhl/advanced-2026-pwhl-drafting-expected-goals>. Uses xG (location, angle, shot type) for NCAA prospects; no method published.
- Frontiers in Sports and Active Living (2025), shot selection in OUA, PWHL, and NHL (6,088 PWHL attempts): <https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2025.1648099/full>. A shot-pattern study, not an xG model.

General xG methodology:

10. Evolving-Hockey, "A New Expected Goals Model for Predicting Goals in the NHL" (XGBoost, separate models per strength state): <https://evolving-hockey.com/blog/a-new-expected-goals-model-for-predicting-goals-in-the-nhl/>
11. Hockey Alchemy, "How Our Expected Goals (xG) Model Works": <https://www.hockeyalchemy.com/blog/how-our-expected-goals-model-works>
12. HockeyStats, "Expected Goals" methodology (why missed shots are usually included): <https://hockeystats.com/methodology/expected-goals>
13. Davis et al., "Biases in Expected Goals Models Confound Finishing Ability": <https://dtai.cs.kuleuven.be/sports/blog/biases-in-expected-goals-models-confound-finishing-ability/> (paper: <https://arxiv.org/pdf/2401.09940>)
