# Databricks notebook source
# MAGIC %md
# MAGIC # xG model v1
# MAGIC
# MAGIC Step 4 of `docs/plans/xg-model.md`: a model that beats the step 3 baselines.
# MAGIC The bar, on the 2026 test season: log loss below 0.2489, AUC above 0.716
# MAGIC (distance + angle).
# MAGIC
# MAGIC **What this notebook does:**
# MAGIC 1. Picks how distance goes into the model, using calibration by distance band.
# MAGIC 2. Adds features one at a time and keeps each only if it helps on held-out
# MAGIC    seasons.
# MAGIC 3. Compares against gradient boosting.
# MAGIC 4. Tests rescaling each season so total xG tracks goals to date.
# MAGIC
# MAGIC **Validation, then test:** every choice (distance form, features, logistic vs
# MAGIC boosting) is made on the 2025 season, with a model trained on 2024. The 2026
# MAGIC season is shown alongside but never used to choose, so its scores are a fair
# MAGIC test of v1. Choosing on the season you report would flatter the result.
# MAGIC
# MAGIC **How to run:** open it from the repo's Git folder, check the widgets at the
# MAGIC top, and click **Run all**. Every model is logged to MLflow, in the experiment
# MAGIC the `experiment` widget names. Nothing here writes to any table.

# COMMAND ----------

import sys
from collections.abc import Callable
from pathlib import Path

import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.pipeline import Pipeline

# A Git folder usually puts the repo root on sys.path. In case it doesn't, find the
# nearest folder above the working directory that holds ml/xg/.
repo_root = next(
    (
        str(path)
        for path in [Path.cwd(), *Path.cwd().parents]
        if (path / "ml/xg").is_dir()
    ),
    None,
)
if repo_root and repo_root not in sys.path:
    sys.path.append(repo_root)

from ml.xg import data, metrics, model

current_user = spark.sql("select current_user()").first()[0]
dbutils.widgets.text("gold_schema", "dev.dbt_apetry_gold")
dbutils.widgets.text("silver_schema", "dev.dbt_apetry_silver")
dbutils.widgets.text("experiment", f"/Users/{current_user}/puckmesh-xg")
gold_schema = dbutils.widgets.get("gold_schema")
silver_schema = dbutils.widgets.get("silver_schema")

# A workspace experiment, not the notebook's own: notebooks in a Git folder can't
# hold MLflow experiments, and this way every xG notebook logs to one place.
mlflow.set_experiment(dbutils.widgets.get("experiment"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The data
# MAGIC
# MAGIC The same training set as the baselines (shots at a goalie, regular season and
# MAGIC playoffs), plus the derived columns the model uses: log-distance, a three-way
# MAGIC strength (advantage / even / shorthanded), a capped score difference, and the
# MAGIC period with overtime grouped.

# COMMAND ----------

shots = model.add_features(
    spark.sql(data.shots_query(gold_schema, silver_schema)).toPandas()
)
folds = data.season_folds(shots)
# Choices are made on every fold but the last; the last is the test season.
selection_folds, latest = folds[:-1], folds[-1]

by_season = (
    shots.groupby(["season_year", "season_name"])
    .agg(shots=("is_goal", "size"), goals=("is_goal", "sum"))
    .assign(goal_rate=lambda df: (df["goals"] / df["shots"]).round(3))
    .reset_index()
)
display(by_season)

# COMMAND ----------

# MAGIC %md
# MAGIC Every model below is logged as a *nested run* under one parent run for this
# MAGIC notebook run, with its settings as params and its scores per test season as
# MAGIC metrics (e.g. `log_loss_2026`). Compare them in the experiment's table view.

# COMMAND ----------

mlflow.end_run()  # In case an earlier, interrupted run left one open.
parent_run = mlflow.start_run(run_name="xg_model_v1")
# Logged now, so a run that fails partway still shows what it ran on.
mlflow.log_params(
    {
        "gold_schema": gold_schema,
        "silver_schema": silver_schema,
        "selection_years": ", ".join(str(f.test_year) for f in selection_folds),
        "test_year": latest.test_year,
    }
)


def log_candidate(name: str, params: dict, scores: dict[int, dict]) -> None:
    """One nested MLflow run: params, plus each test year's metrics."""
    with mlflow.start_run(run_name=name, nested=True):
        mlflow.log_params(params)
        mlflow.log_metrics(
            {
                f"{metric}_{year}": value
                for year, score in scores.items()
                for metric, value in score.items()
                if metric in ("log_loss", "brier", "auc", "xg_per_goal")
            }
        )


def fold_scores(fit: Callable[..., Pipeline], **kwargs) -> dict[int, dict]:
    """Fit on each fold's train seasons and score its test season."""
    return {
        fold.test_year: metrics.score(
            fold.test["is_goal"], model.predict(fit(fold.train, **kwargs), fold.test)
        )
        for fold in folds
    }


# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. How distance goes in
# MAGIC
# MAGIC The baselines over-predicted long shots (3.5% vs 2.4% at 45-70 ft in 2026). Two
# MAGIC fixes to try: distance on a log scale, which gives the close range more of the
# MAGIC spline's flexibility, and fewer knots, which make the far end stiffer. Pick on
# MAGIC the 2025 rows. The table below the scores shows why neither fixes it fully: the
# MAGIC long-range goal rate itself fell season by season, so a model trained on older
# MAGIC seasons runs high there.

# COMMAND ----------

distance_forms = {
    "distance, 5 knots (baseline)": {"distance": "distance_ft", "distance_knots": 5},
    "distance, 3 knots": {"distance": "distance_ft", "distance_knots": 3},
    "log distance, 3 knots": {"distance": "log_distance", "distance_knots": 3},
    "log distance, 4 knots": {"distance": "log_distance", "distance_knots": 4},
    "log distance, 5 knots": {"distance": "log_distance", "distance_knots": 5},
}
distance_results = []
for name, form in distance_forms.items():
    scores = fold_scores(model.fit_logistic, features=[], **form)
    log_candidate(name, {"model": "logistic", "features": "", **form}, scores)
    distance_results += [
        {"form": name, "test_year": year} | score for year, score in scores.items()
    ]
distance_results = pd.DataFrame(distance_results)
display(distance_results.round(4))

# COMMAND ----------

long_range_by_season = (
    shots.assign(band=metrics.distance_band(shots["distance_ft"]))
    .pivot_table(
        index="band",
        columns="season_year",
        values="is_goal",
        aggfunc="mean",
        observed=False,
    )
    .round(3)
)
print("Actual goal rate by distance band and season")
display(long_range_by_season.reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Adding features, one at a time
# MAGIC
# MAGIC Starting from log distance (4 knots) and angle, each candidate is added in turn
# MAGIC and kept only if log loss drops on the 2025 validation season. "Default" shot
# MAGIC type (21-46% of shots by season) is its own category. Section 4 then checks the
# MAGIC kept set on 2026, which played no part in choosing it.
# MAGIC
# MAGIC | Candidate | What it is |
# MAGIC |---|---|
# MAGIC | `shot_type` | Wrist, snap, slap, backhand, tip, or "Default" (not recorded) |
# MAGIC | `is_rebound` | The team's previous shot was within a few seconds |
# MAGIC | `strength` | Advantage, even or shorthanded for the shooting team |
# MAGIC | `is_3v3` | Three skaters a side (overtime), which `strength` counts as even |
# MAGIC | `score_diff_capped` | Shooting team's lead, capped at ±3 |
# MAGIC | `period_group` | 1, 2, 3 or overtime |

# COMMAND ----------

v1_features, selection = model.forward_select(selection_folds, model.FEATURE_STEPS)
for step, step_rows in selection.groupby("step", sort=False):
    log_candidate(
        step,
        {
            "model": "logistic",
            "features": step_rows["features"].iloc[0],
            "is_kept": bool(step_rows["is_kept"].iloc[0]),
        },
        {row["test_year"]: row for row in step_rows.to_dict("records")},
    )
print("Kept:", v1_features)
display(
    selection[
        ["step", "is_kept", "test_year", "log_loss", "brier", "auc", "xg_per_goal"]
    ].round(4)
)

# COMMAND ----------

# Dots, as in the baselines notebook: the differences are small.
fig, ax = plt.subplots(figsize=(10, 4))
steps = list(dict.fromkeys(selection["step"]))
for fold in selection_folds:
    fold_rows = selection[selection["test_year"] == fold.test_year].set_index("step")
    ax.plot(
        steps,
        fold_rows.loc[steps, "log_loss"],
        marker="o",
        label=f"test {fold.test_year}",
    )
ax.set_ylabel("log loss (lower is better)")
ax.legend()
ax.set_title("Each candidate feature, in order")
fig.autofmt_xdate(rotation=20)
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Gradient boosting
# MAGIC
# MAGIC scikit-learn's HistGradientBoosting on the same features. Trees find
# MAGIC interactions on their own (e.g. tips matter more close in), but with ~1,400
# MAGIC goals they can also fit noise. The plan keeps it only if it clearly beats
# MAGIC logistic regression. The `logistic v1` rows for 2026 are v1's test score.

# COMMAND ----------

comparison_scores = {
    "logistic v1": fold_scores(model.fit_logistic, features=v1_features),
    "gradient boosting": fold_scores(model.fit_gradient_boosting, features=v1_features),
}
log_candidate(
    "gradient boosting",
    {"model": "hist_gradient_boosting", "features": ", ".join(v1_features)},
    comparison_scores["gradient boosting"],
)
comparison = pd.DataFrame(
    [
        {"model": name, "test_year": year} | score
        for name, scores in comparison_scores.items()
        for year, score in scores.items()
    ]
)
display(comparison.round(4))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Rescaling to goals to date
# MAGIC
# MAGIC The league's goal rate moves between seasons, so a model trained on past
# MAGIC seasons predicts a total that's 5-10% off. Rescaling shifts every shot's xG so
# MAGIC the season's total tracks its goals so far. Each game day uses only earlier
# MAGIC days, as it would live, and 50 pseudo-goals keep the first weeks steady
# MAGIC (set in advance; 20 and 100 are shown to see how much it matters).
# MAGIC Watch `xg_per_goal`: rescaling should bring it near 1.0 without hurting log
# MAGIC loss.

# COMMAND ----------

rescaling = []
for fold in folds:
    xg = model.predict(model.fit_logistic(fold.train, v1_features), fold.test)
    for prior_goals in (20, 50, 100):
        rescaled = model.rescale_to_date(fold.test, xg, prior_goals=prior_goals)
        rescaling.append(
            {"test_year": fold.test_year, "prior_goals": prior_goals}
            | metrics.score(fold.test["is_goal"], rescaled)
        )
    rescaling.append(
        {"test_year": fold.test_year, "prior_goals": "none (raw v1)"}
        | metrics.score(fold.test["is_goal"], xg)
    )
rescaling = pd.DataFrame(rescaling)
with mlflow.start_run(run_name="v1 rescaled, 50 prior goals", nested=True):
    mlflow.log_params(
        {"model": "logistic", "features": ", ".join(v1_features), "prior_goals": 50}
    )
    mlflow.log_metrics(
        {
            f"{metric}_{row['test_year']}": row[metric]
            for row in rescaling[rescaling["prior_goals"] == 50].to_dict("records")
            for metric in ("log_loss", "brier", "auc", "xg_per_goal")
        }
    )
display(rescaling.round(4))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Model v1 on the latest season
# MAGIC
# MAGIC Trained on every season before the latest, scored on the latest. Calibration by
# MAGIC distance band, raw and rescaled; points on the diagonal are well calibrated.

# COMMAND ----------

v1 = model.fit_logistic(latest.train, v1_features)
v1_xg = model.predict(v1, latest.test)
calibration = metrics.calibration_by_distance(latest.test, v1_xg)
calibration_rescaled = metrics.calibration_by_distance(
    latest.test, model.rescale_to_date(latest.test, v1_xg)
)
calibration["rescaled_rate"] = calibration_rescaled["predicted_rate"]
display(calibration.round(3))

fig, ax = plt.subplots(figsize=(5, 5))
top = calibration[["actual_rate", "predicted_rate", "rescaled_rate"]].max().max() * 1.1
ax.plot([0, top], [0, top], color="grey", linestyle="--")
ax.scatter(calibration["predicted_rate"], calibration["actual_rate"], label="raw")
ax.scatter(calibration["rescaled_rate"], calibration["actual_rate"], label="rescaled")
for _, row in calibration.iterrows():
    ax.annotate(row["band"], (row["predicted_rate"], row["actual_rate"]), fontsize=8)
ax.set_xlabel("predicted goal rate")
ax.set_ylabel("actual goal rate")
ax.set_title(f"v1, test {latest.test_year}")
ax.legend()
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC How each feature moves xG, for a shot from the slot (20 ft, straight on) at even
# MAGIC strength, unless the row says otherwise.

# COMMAND ----------

slot = pd.DataFrame(
    {
        "distance_ft": 20.0,
        "angle_deg": 0.0,
        "shot_type": "Wrist",
        "is_rebound": False,
        "strength_state": "5v5",
        "score_diff": 0,
        "period": 2,
    },
    index=[0],
)
variants = {
    "wrist shot": {},
    "tip": {"shot_type": "Tip"},
    "slap shot": {"shot_type": "Slap"},
    "shot type not recorded": {"shot_type": "Default"},
    "rebound": {"is_rebound": True},
    "power play (5v4)": {"strength_state": "5v4"},
    "shorthanded (4v5)": {"strength_state": "4v5"},
    "3v3 overtime": {"strength_state": "3v3", "period": 4},
    "from 45 ft": {"distance_ft": 45.0},
}
examples = model.add_features(
    pd.concat(
        [slot.assign(**change) for change in variants.values()], ignore_index=True
    )
)
display(
    pd.DataFrame({"shot": list(variants), "xg": model.predict(v1, examples).round(3)})
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Log the model and summarize
# MAGIC
# MAGIC The v1 pipeline above is logged to the parent run as an MLflow model, so step 6
# MAGIC can load the exact thing that was evaluated. It's trained on seasons before the
# MAGIC latest; the model that scores new games will be retrained on every season.

# COMMAND ----------

v1_scores = comparison_scores["logistic v1"]
mlflow.log_params(
    {
        "v1_features": ", ".join(v1_features),
        "distance": "log_distance",
        "distance_knots": 4,
        "train_years": ", ".join(
            map(str, sorted(latest.train["season_year"].unique()))
        ),
    }
)
mlflow.log_metrics(
    {
        f"{metric}_{year}": score[metric]
        for year, score in v1_scores.items()
        for metric in ("log_loss", "brier", "auc", "xg_per_goal")
    }
)
# Cloudpickle is MLflow's default on Databricks; naming it keeps local runs the same.
# (The local default, skops, rejects the spline's scipy types.) It's our own model, so
# unpickling it is safe.
mlflow.sklearn.log_model(
    v1,
    name="model",
    input_example=latest.test.head(5)[v1.feature_names_in_],
    serialization_format="cloudpickle",
)
mlflow.end_run()

# COMMAND ----------

# Plain text, to paste back for analysis.
print(f"MLflow run: {parent_run.info.run_id}")
print()
print(by_season.to_string(index=False))
print()
print(
    distance_results[["form", "test_year", "log_loss", "auc", "xg_per_goal"]]
    .round(4)
    .to_string(index=False)
)
print()
print(long_range_by_season.to_string())
print()
print("Kept:", v1_features)
print(
    selection[["step", "is_kept", "test_year", "log_loss", "auc", "xg_per_goal"]]
    .round(4)
    .to_string(index=False)
)
print()
print(
    comparison[["model", "test_year", "log_loss", "auc", "xg_per_goal"]]
    .round(4)
    .to_string(index=False)
)
print()
print(
    rescaling[["test_year", "prior_goals", "log_loss", "auc", "xg_per_goal"]]
    .round(4)
    .to_string(index=False)
)
print()
print(calibration.round(3).to_string(index=False))
