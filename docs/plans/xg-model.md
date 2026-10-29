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
  - Empty nets were undercounted: 9 found vs 94 flagged by the league. Fixed by taking the flag from the goal event (5a).
  - Shot type is recorded more often in later seasons (5b), so keep it only if it helps on held-out data.

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
    - Which penalties change strength. "No power play" doesn't mean "no change in strength": coincidental minors don't create a power play, but they still take a skater off each team (4-on-4).

      | Penalty | Takes a skater off? | Ends early on a goal against? |
      |---|---|---|
      | Minor, `pp` = true | Yes | Yes. The penalty that started first ends, on a goal the league flags `is_power_play`. |
      | Minor, `pp` = false (coincidental) | Yes, so equal minors on both teams give 4v4. But if a power-play penalty was called at the same moment, they're replaced on the ice. | No |
      | Major or match | Yes, whatever the `pp` flag says. A major with a game misconduct often has no flag but still creates a power play (audit 6c). | No |
      | Majors on both teams at the same moment (a fight) | No; replacements come on | No |
      | Misconduct (10 or 20 min), or a penalty-shot penalty | No, whatever the flag says | n/a |

    - Why the league's goal flag decides which penalty ends: the league already marks power-play goals. Using that mark avoids circular logic, where whether a penalty ended depends on the strength state we're still computing. The on-ice lists stay an independent check.
    - Double minors are recorded as two 2-minute minors (5d). Two minors on one player at the same moment run back to back (5v4 for 4 minutes), not at once. A power-play goal ends only the one running.
    - Majors and match penalties: run the full 5 minutes whatever happens.
    - Two in the box at most: a third penalty waits until the first one ends, so a team never drops below 3 skaters.
    - On a 5v3 goal, only the penalty that started first ends.
    - Short-handed goals end nothing.
    - Penalties carry across period breaks; `game_seconds` already runs on through the game.
    - Regular-season overtime is 3-on-3, so a penalty adds a skater for the other team (4v3) instead of removing one. Playoff overtime is 5-on-5. Confirmed by 5c.
    - Same-second order: a penalty covers shots after it in `event_index` and strictly later on the clock. A shot in the same second as the call doesn't count it; the on-ice lists agree (audit 6c, games 164, 185, 193, 201).
    - Pulled goalies: from `stg_pwhl__goalie_changes`, the team with an empty net counts as 6 skaters (38 goals scored 6v5 in 5c). Delayed-penalty pulls may not be recorded; that's a known gap.
  - **Tests:**
    - Goals' `is_power_play` / `is_short_handed` flags.
    - The on-ice player lists on each goal, which count skaters only (5c). Skip goals whose `against` list is empty (~2.5%), and allow a small mismatch rate: a few lists disagree with the league's own flags.
- Maybe a rough rush flag (a shot within a few seconds of an event in another zone), if step 1 shows the event timing supports it.
- Why the features go in dbt: they get tested and documented there, and the ratings and predictions models can reuse them. The Python side reads one table.

- **Built (PR #13):**
  - `int_penalties_timed`, plus `skaters_for`, `skaters_against` and `strength_state` on `fct_shots`.
  - Matches the league's on-ice lists on 97.6% of goals (37 mismatches of ~1,550; see [xg-audit.md](xg-audit.md), section 6).
  - The reconciliation test fails above 45.

### 3. Training set and baselines

**Built:**
- **Code:** `ml/xg/` (training set query, forward-chaining season folds, four baselines, metrics).
- **Notebook:** `notebooks/xg_baselines.py`, which shows the data, the baselines, calibration, an xG map, and the shots where the model and reality disagree.
- **Running it:** in Databricks, through a Git folder. The scheduled pipeline never runs the notebook; daily scoring (step 7) will call the same modules from GitHub Actions.
- **Results** (notebook run on dev, after the empty-net and strength fixes):

  | Baseline | Log loss, test 2025 | AUC, test 2025 | xG/goals, test 2025 | Log loss, test 2026 | AUC, test 2026 | xG/goals, test 2026 |
  |---|---|---|---|---|---|---|
  | League average | 0.2891 | 0.500 | 0.87 | 0.2685 | 0.500 | 1.04 |
  | Quality flag | 0.2786 | 0.630 | 0.88 | 0.2564 | 0.647 | 1.05 |
  | Distance | 0.2752 | 0.674 | 0.89 | 0.2510 | 0.702 | 1.06 |
  | Distance + angle | 0.2717 | 0.697 | 0.90 | 0.2489 | 0.716 | 1.07 |

  Test sets: 5,646 shots and 474 goals in 2025; 7,398 shots and 561 goals in 2026.

  Calibration by distance band, distance + angle, test 2026:

  | Band | Shots | Goals | Actual rate | Predicted rate |
  |---|---|---|---|---|
  | 0–10 ft | 827 | 133 | 0.161 | 0.165 |
  | 10–20 ft | 1,625 | 195 | 0.120 | 0.129 |
  | 20–30 ft | 1,284 | 114 | 0.089 | 0.077 |
  | 30–45 ft | 1,682 | 77 | 0.046 | 0.052 |
  | 45–70 ft | 1,739 | 42 | 0.024 | 0.035 |
  | 70+ ft | 241 | 0 | 0.000 | 0.018 |

- **Takeaways:**
  1. **Each step adds information, in both test seasons.** Distance + angle cuts log loss 6–7% from the league average, with AUC 0.70–0.72. That's normal for a location-only model of shots on goal: NHL models reach 0.75–0.80, but they also include misses, which are easier to tell apart. It already beats the league's own quality-chance zone.
  2. **The league's goal rate shifts by season** (7.3% in 2024, 8.4% in 2025, 7.6% in 2026; season years, regular season plus playoffs, after the empty-net fix), so total xG runs 5–10% low or high in a new season. League average shows the same, so it's the base rate, not the model. Step 4 tries rescaling each season so xG totals match goals to date. Decide before publishing.
  3. **Long shots are over-predicted:** 3.5% vs 2.4% at 45–70 ft, and 1.8% vs 0 of 241 beyond 70 ft. Likely causes are the remaining coordinate noise and a spline that flattens out too high at the far end. Step 4 tries log-distance or fewer knots.
- **The bar for model v1** (test 2026): log loss below 0.2489, AUC above 0.716, and calibration close in every distance band.


- Train on unblocked, non-empty-net shots in regulation and overtime. Leave out shootouts and penalty shots, which are already separate event types.
- Baselines to beat: league-average goal rate, then distance only, then distance + angle (roughly the 18 Skaters model [1]).

### 4. Model v1

- Logistic regression with splines on distance and angle, plus shot type, rebound, and strength state.
- One comparison with gradient boosting (LightGBM or XGBoost) [10]. Keep it only if it clearly beats logistic on held-out data.
- Empty-net shots get their own model or a fixed value, as Evolving-Hockey and Hockey Alchemy do [10][11].

**Built:**
- **Code:** `ml/xg/model.py` (derived features, the logistic and gradient-boosting fits, forward selection, season rescaling). `shots_query` now joins `fct_games` for `game_date`, which rescaling orders by.
- **Notebook:** `notebooks/xg_model_v1.py`. Each candidate is a nested MLflow run under one parent run, in the workspace experiment the `experiment` widget names (default `/Users/<you>/puckmesh-xg`). The v1 pipeline is logged to the parent run as an MLflow model. It takes the columns `model.add_features` makes, so scoring calls that first.
- **Results** (local run of the notebook on dev, 17,940 shots and 1,394 goals; confirm with the Databricks run):

  | Model | Log loss, test 2025 | AUC, test 2025 | xG/goals, test 2025 | Log loss, test 2026 | AUC, test 2026 | xG/goals, test 2026 |
  |---|---|---|---|---|---|---|
  | Distance + angle (step 3 bar) | 0.2717 | 0.697 | 0.90 | 0.2489 | 0.716 | 1.07 |
  | Log distance (4 knots) + angle | 0.2710 | 0.701 | 0.90 | 0.2481 | 0.719 | 1.07 |
  | + shot type | 0.2701 | 0.710 | 0.87 | 0.2475 | 0.722 | 1.07 |
  | + `is_rebound` | 0.2684 | 0.714 | 0.87 | 0.2446 | 0.733 | 1.09 |
  | **+ strength (v1)** | **0.2670** | **0.720** | 0.87 | **0.2442** | **0.738** | 1.10 |
  | v1, rescaled to goals to date | 0.2665 | 0.720 | 0.96 | 0.2440 | 0.737 | 1.00 |
  | Gradient boosting, v1 features | 0.2698 | 0.701 | 0.88 | 0.2447 | 0.731 | 1.09 |

  Calibration by distance band, v1, test 2026:

  | Band | Shots | Goals | Actual rate | Predicted | Rescaled |
  |---|---|---|---|---|---|
  | 0–10 ft | 827 | 133 | 0.161 | 0.184 | 0.169 |
  | 10–20 ft | 1,625 | 195 | 0.120 | 0.124 | 0.113 |
  | 20–30 ft | 1,284 | 114 | 0.089 | 0.081 | 0.073 |
  | 30–45 ft | 1,682 | 77 | 0.046 | 0.054 | 0.049 |
  | 45–70 ft | 1,739 | 42 | 0.024 | 0.035 | 0.032 |
  | 70+ ft | 241 | 0 | 0.000 | 0.021 | 0.019 |

- **Takeaways:**
  1. **v1 clears the bar:** log loss 0.2442 and AUC 0.738 on 2026, against 0.2489 and 0.716. Every choice (distance form, features, logistic vs boosting) was made on 2025 with a model trained on 2024; 2026 played no part, so it's a fair test. Rebounds help most, then strength, then shot type.
  2. **Kept:** shot type ("Default" as its own category), `is_rebound`, and strength as advantage / even / shorthanded. A feature stays only if log loss drops on 2025. **Dropped:** the full `strength_state` (too few shots per cell), `score_diff`, `period`. Also checked, outside the notebook, with no gain above 0.0002: home team, defender shooting, time since the team's previous shot, and how far a rebound moved across the crease. A rush flag would need new dbt work; a v2 candidate.
  3. **Long shots stay over-predicted, and it's the data, not the spline.** The 45–70 ft goal rate fell from 4.3% to 3.3% to 2.4% across the three seasons, so a model trained on older seasons runs high there. Log distance and fewer knots barely move it. Recorded as a known issue.
  4. **Gradient boosting doesn't beat logistic,** so v1 is logistic, as planned. No LightGBM or XGBoost.
  5. **Rescaling fixes totals, and log loss barely changes.** Each game day's factor comes from earlier days only, shrunk toward 1 with 50 pseudo-goals (set in advance, not tuned) and applied to the log-odds. Whether published xG is rescaled is still to decide (before step 6).
  6. **Sample size changed with the empty-net fix:** 17,940 shots and 1,394 goals now, against the audit's 18,022 and 1,476. The 82 removed are all empty-net goals.

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

1. **New dependencies (decided):**
   - `requirements-ml.txt` with scikit-learn, pandas, and mlflow, created with the first ML code.
   - Installed in one command with `requirements.txt` (`pip install -r requirements.txt -r requirements-ml.txt`), so pip picks shared versions such as `databricks-sdk` that fit both. Only the jobs that need ML get it.
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
