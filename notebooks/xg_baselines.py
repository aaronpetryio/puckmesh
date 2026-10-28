# Databricks notebook source
# MAGIC %md
# MAGIC # xG baselines
# MAGIC
# MAGIC Step 3 of `docs/plans/xg-model.md`: the bar a real expected-goals model has to
# MAGIC beat.
# MAGIC
# MAGIC **What xG means here:** the probability that a shot on goal becomes a goal.
# MAGIC HockeyTech records no missed shots, so this is P(goal | shot on goal) and isn't
# MAGIC comparable to NHL xG, which also counts misses.
# MAGIC
# MAGIC **How to run:** clone the repo as a Git folder in Databricks, open this
# MAGIC notebook, check the two schema widgets at the top, and click **Run all**. The
# MAGIC model code lives in `ml/xg/`; this notebook only loads data, calls it, and draws
# MAGIC charts.
# MAGIC Nothing here writes to any table.

# COMMAND ----------

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# A Git folder puts the repo root on sys.path; this covers running from elsewhere.
repo_root = str(Path.cwd().parent)
if repo_root not in sys.path:
    sys.path.append(repo_root)

from ml.xg import baselines, data, metrics

dbutils.widgets.text("gold_schema", "dev.dbt_apetry_gold")
dbutils.widgets.text("silver_schema", "dev.dbt_apetry_silver")
gold_schema = dbutils.widgets.get("gold_schema")
silver_schema = dbutils.widgets.get("silver_schema")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The data
# MAGIC
# MAGIC Shots at a goalie (no blocked shots, no empty nets), regular season and
# MAGIC playoffs.
# MAGIC A *season year* is a regular season plus its playoffs: the unit we split on.

# COMMAND ----------

shots = spark.sql(data.shots_query(gold_schema, silver_schema)).toPandas()

by_season = (
    shots.groupby(["season_year", "season_name"])
    .agg(shots=("is_goal", "size"), goals=("is_goal", "sum"))
    .assign(goal_rate=lambda df: (df["goals"] / df["shots"]).round(3))
    .reset_index()
)
display(by_season)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Where goals come from
# MAGIC
# MAGIC Every shot is turned to attack the net on the right (x = 89 ft). Grey dots are
# MAGIC saves, red dots are goals. Coordinates are approximate: the league's grid is
# MAGIC stylized, and a few percent of shots are placed on the wrong half.

# COMMAND ----------


def draw_half_rink(ax: plt.Axes) -> None:
    ax.axvline(89, color="red", linewidth=1)  # goal line
    ax.axvline(25, color="blue", linewidth=2)  # blue line
    ax.plot([89, 92.3], [-3, -3], color="black")  # net, roughly
    ax.plot([89, 92.3], [3, 3], color="black")
    ax.plot([92.3, 92.3], [-3, 3], color="black")
    ax.set_xlim(0, 100)
    ax.set_ylim(-42.5, 42.5)
    ax.set_aspect("equal")
    ax.set_xlabel("feet from center ice")


saves = shots[~shots["is_goal"]]
goals = shots[shots["is_goal"]]
fig, ax = plt.subplots(figsize=(10, 8.5))
draw_half_rink(ax)
ax.scatter(saves["x_ft"], saves["y_ft"], s=2, color="lightgrey", label="save")
ax.scatter(goals["x_ft"], goals["y_ft"], s=6, color="crimson", label="goal")
ax.legend(loc="upper left")
ax.set_title(f"{len(shots):,} shots, {len(goals):,} goals")
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC Goal rate by distance. This curve is what the distance baseline tries to learn.

# COMMAND ----------

by_distance = metrics.calibration_by_distance(shots, np.zeros(len(shots)))
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(by_distance["band"].astype(str), by_distance["actual_rate"], color="steelblue")
for i, row in by_distance.iterrows():
    ax.annotate(f"{row['shots']:,}", (i, row["actual_rate"]), ha="center", va="bottom")
ax.set_ylabel("goal rate")
ax.set_title("Goal rate by distance (labels: shots)")
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Baselines
# MAGIC
# MAGIC Four models, from knowing nothing to knowing distance and angle:
# MAGIC
# MAGIC | Baseline | What it knows |
# MAGIC |---|---|
# MAGIC | `league_average` | Nothing: every shot gets the league goal rate |
# MAGIC | `quality_flag` | The league's "quality chance" zone (a benchmark only) |
# MAGIC | `distance` | Distance to the net, as a smooth curve (spline) |
# MAGIC | `distance_angle` | Distance and angle (roughly the 18 Skaters PWHL model) |
# MAGIC
# MAGIC **Folds:** train on earlier season years, test on the next one, the way the
# MAGIC model will be used. **Lower log loss and Brier are better; higher AUC is
# MAGIC better;** `xg_per_goal` near 1.0 means the total number of goals predicted is
# MAGIC right.

# COMMAND ----------

folds = data.season_folds(shots)
results = []
predictions = {}
for fold in folds:
    for name, baseline in baselines.BASELINES.items():
        xg = baseline(fold.train, fold.test)
        predictions[(fold.test_year, name)] = xg
        results.append(
            {"test_year": fold.test_year, "baseline": name}
            | metrics.score(fold.test["is_goal"], xg)
        )
results = pd.DataFrame(results)
display(results.round(4))

# COMMAND ----------

fig, ax = plt.subplots(figsize=(9, 4))
names = list(baselines.BASELINES)
width = 0.8 / len(folds)
for i, fold in enumerate(folds):
    fold_results = results[results["test_year"] == fold.test_year].set_index("baseline")
    ax.bar(
        np.arange(len(names)) + i * width,
        fold_results.loc[names, "log_loss"],
        width,
        label=f"test {fold.test_year}",
    )
ax.set_xticks(np.arange(len(names)) + width * (len(folds) - 1) / 2, names)
ax.set_ylim(results["log_loss"].min() * 0.95, results["log_loss"].max() * 1.02)
ax.set_ylabel("log loss (lower is better)")
ax.legend()
ax.set_title("Baselines by test season")
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Calibration
# MAGIC
# MAGIC For the latest test season: does `distance_angle` predict the right goal rate in
# MAGIC each distance band? Points on the diagonal are well calibrated.

# COMMAND ----------

latest = folds[-1]
best_xg = predictions[(latest.test_year, "distance_angle")]
calibration = metrics.calibration_by_distance(latest.test, best_xg)
display(calibration.round(3))

fig, ax = plt.subplots(figsize=(5, 5))
top = calibration[["actual_rate", "predicted_rate"]].max().max() * 1.1
ax.plot([0, top], [0, top], color="grey", linestyle="--")
ax.scatter(calibration["predicted_rate"], calibration["actual_rate"])
for _, row in calibration.iterrows():
    ax.annotate(row["band"], (row["predicted_rate"], row["actual_rate"]), fontsize=8)
ax.set_xlabel("predicted goal rate")
ax.set_ylabel("actual goal rate")
ax.set_title(f"distance_angle, test {latest.test_year}")
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. What the model learned
# MAGIC
# MAGIC `distance_angle`, trained on every season before the latest, scored over a grid
# MAGIC of the attacking zone. Darker means a shot from there is more likely to score.

# COMMAND ----------

grid_x, grid_y = np.meshgrid(np.linspace(25, 99, 150), np.linspace(-42, 42, 150))
grid = pd.DataFrame({"x_ft": grid_x.ravel(), "y_ft": grid_y.ravel()})
grid["distance_ft"] = np.hypot(89 - grid["x_ft"], grid["y_ft"])
grid["angle_deg"] = np.degrees(np.arctan2(grid["y_ft"].abs(), 89 - grid["x_ft"]))
grid_xg = baselines.distance_angle(latest.train, grid)

fig, ax = plt.subplots(figsize=(10, 8.5))
draw_half_rink(ax)
mesh = ax.pcolormesh(
    grid_x, grid_y, grid_xg.reshape(grid_x.shape), cmap="Reds", shading="auto"
)
fig.colorbar(mesh, ax=ax, label="xG")
ax.set_title("xG by location (distance_angle)")
display(fig)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Where the model and reality disagree
# MAGIC
# MAGIC From the latest test season. High-xG saves and low-xG goals are where the next
# MAGIC features (rebounds, strength state, shot type) should help, or where the
# MAGIC coordinates are wrong.

# COMMAND ----------

examples = latest.test.assign(xg=best_xg)
example_columns = [
    "season_name",
    "game_id",
    "period",
    "distance_ft",
    "angle_deg",
    "shot_type",
    "strength_state",
    "is_rebound",
    "xg",
]
print("Highest-xG shots that were saved")
display(examples[~examples["is_goal"]].nlargest(10, "xg")[example_columns])

# COMMAND ----------

print("Lowest-xG shots that scored")
display(examples[examples["is_goal"]].nsmallest(10, "xg")[example_columns])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Summary to share
# MAGIC
# MAGIC Plain text, to paste back for analysis.

# COMMAND ----------

print(results.round(4).to_string(index=False))
print()
print(calibration.round(3).to_string(index=False))
