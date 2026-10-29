# Databricks notebook source
# MAGIC %md
# MAGIC # xG model v1: sanity checks
# MAGIC
# MAGIC Step 5 of `docs/plans/xg-model.md`. Step 4 showed v1 scores well; this checks
# MAGIC that its numbers look right where people will read them, before step 6
# MAGIC publishes them:
# MAGIC 1. Total xG vs goals, and calibration, per season.
# MAGIC 2. Goal rates by strength state.
# MAGIC 3. The top shooters and goalies by xG.
# MAGIC
# MAGIC **Which predictions:** each season is scored by a v1 model fit on the *other*
# MAGIC seasons (leave one season out), so no shot is scored by a model that saw it.
# MAGIC That's how step 6 publishes past seasons. Unlike step 4's folds it also
# MAGIC scores 2024, at the cost of training on later seasons, so step 4's test scores
# MAGIC stay the fair measure of v1. The player tables use rescaled xG, as published
# MAGIC (decision 5).
# MAGIC
# MAGIC **How to run:** open it from the repo's Git folder, check the widgets at the
# MAGIC top, and click **Run all**. One MLflow run holds the scores and tables. Nothing
# MAGIC here writes to any table.

# COMMAND ----------

import sys
import tempfile
from pathlib import Path

import mlflow
import pandas as pd

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

from ml.xg import data, evaluate, metrics, model

current_user = spark.sql("select current_user()").first()[0]
dbutils.widgets.text("gold_schema", "dev.dbt_apetry_gold")
dbutils.widgets.text("silver_schema", "dev.dbt_apetry_silver")
dbutils.widgets.text("experiment", f"/Users/{current_user}/puckmesh-xg")
gold_schema = dbutils.widgets.get("gold_schema")
silver_schema = dbutils.widgets.get("silver_schema")
mlflow.set_experiment(dbutils.widgets.get("experiment"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Score every shot

# COMMAND ----------

shots = model.add_features(
    spark.sql(data.shots_query(gold_schema, silver_schema)).toPandas()
)
xg_raw = model.out_of_fold(shots, model.V1_FEATURES)
xg = model.rescale_to_date(shots, xg_raw)
shots = shots.assign(xg_raw=xg_raw, xg=xg)

players = spark.sql(data.players_query(gold_schema)).toPandas()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Per season
# MAGIC
# MAGIC Raw xG/goals should sit within 5-10% of 1 (step 3 found the league's goal
# MAGIC rate moves that much between seasons); rescaled should be close to 1.

# COMMAND ----------

season_scores = pd.DataFrame(
    [
        {"season_year": year, "xg": kind}
        | metrics.score(season["is_goal"], season[column].to_numpy())
        for year, season in shots.groupby("season_year")
        for kind, column in [("raw", "xg_raw"), ("rescaled", "xg")]
    ]
)
display(season_scores.round(4))

calibration_by_season = pd.concat(
    [
        metrics.calibration_by_distance(season, season["xg"].to_numpy()).assign(
            season_year=year
        )
        for year, season in shots.groupby("season_year")
    ],
    ignore_index=True,
)
display(calibration_by_season.round(3))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Strength state
# MAGIC
# MAGIC Power plays should score more often than even strength, and shorthanded
# MAGIC shots less (or about the same: they're often breakaways). The model only knows
# MAGIC the three-way grouping, so the full states show whether that hides anything.
# MAGIC States with few shots (e.g. 5v3) are noisy.

# COMMAND ----------

strength_rates = evaluate.rates_by(shots, shots["xg"].to_numpy(), "strength")
state_rates = evaluate.rates_by(shots, shots["xg"].to_numpy(), "strength_state")
display(strength_rates.round(3))
display(state_rates.sort_values("shots", ascending=False).round(3))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Shooters
# MAGIC
# MAGIC Top shooters by xG (who gets the chances) and by goals above xG (who finishes
# MAGIC them). The names should look plausible to someone who follows the league.
# MAGIC Pooled xG models credit skilled shooters' goals to "finishing", partly because
# MAGIC they also get better looks than location shows; noted, not solved in v1.

# COMMAND ----------

MIN_SHOTS = 100
TOP_N = 15


def named(table: pd.DataFrame) -> pd.DataFrame:
    """Player names first, then the table."""
    return players.merge(table, on="player_id", how="right")


shooters = named(evaluate.shooter_table(shots, shots["xg"].to_numpy(), MIN_SHOTS))
shooters_by_season = named(
    evaluate.shooter_table(shots, shots["xg"].to_numpy(), 40, by_season=True)
)
top_shooters_xg = shooters.nlargest(TOP_N, "xg")
top_shooters_finishing = shooters.nlargest(TOP_N, "goals_above_xg")
display(top_shooters_xg.round(3))
display(top_shooters_finishing.round(3))
display(
    shooters_by_season.sort_values(["season_year", "xg"], ascending=[True, False])
    .groupby("season_year")
    .head(10)
    .round(3)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Goalies
# MAGIC
# MAGIC Goals saved above expected (GSAx): xG against minus goals against. Shots on
# MAGIC goal only, so a goalie gets no credit for shots that miss.

# COMMAND ----------

MIN_SHOTS_AGAINST = 500

goalies = named(
    evaluate.goalie_table(shots, shots["xg"].to_numpy(), MIN_SHOTS_AGAINST)
).sort_values("gsax", ascending=False)
goalies_by_season = named(
    evaluate.goalie_table(shots, shots["xg"].to_numpy(), 200, by_season=True)
).sort_values(["season_year", "gsax"], ascending=[True, False])
# Top and bottom 10; with 20 or fewer goalies that's all of them, listed once.
goalie_ends = (
    goalies if len(goalies) <= 20 else pd.concat([goalies.head(10), goalies.tail(10)])
)
display(goalie_ends.round(3))
display(goalies_by_season.round(3))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Log and summarize

# COMMAND ----------

mlflow.end_run()  # In case an earlier, interrupted run left one open.
tables = {
    "season_scores": season_scores,
    "calibration_by_season": calibration_by_season,
    "strength_rates": strength_rates,
    "state_rates": state_rates,
    "shooters": shooters,
    "shooters_by_season": shooters_by_season,
    "goalies": goalies,
    "goalies_by_season": goalies_by_season,
}
with mlflow.start_run(run_name="xg_evaluation") as run:
    mlflow.log_params(
        {
            "gold_schema": gold_schema,
            "silver_schema": silver_schema,
            "features": ", ".join(model.V1_FEATURES),
            "folds": "leave one season out",
        }
    )
    mlflow.log_metrics(
        {
            f"{metric}_{row['season_year']}_{row['xg']}": row[metric]
            for _, row in season_scores.iterrows()
            for metric in ("log_loss", "brier", "auc", "xg_per_goal")
        }
    )
    with tempfile.TemporaryDirectory() as folder:
        for name, table in tables.items():
            table.to_csv(Path(folder) / f"{name}.csv", index=False)
        mlflow.log_artifacts(folder, artifact_path="tables")

# COMMAND ----------

# Plain text, to paste back for analysis.
columns = {
    "shooters": ["full_name", "shots", "goals", "xg", "goals_above_xg", "xg_per_shot"],
    "goalies": [
        "full_name",
        "shots_against",
        "goals_against",
        "xg_against",
        "gsax",
        "save_pct",
        "expected_save_pct",
    ],
}
print(f"MLflow run: {run.info.run_id}")
print()
print(
    season_scores[
        ["season_year", "xg", "shots", "goals", "log_loss", "auc", "xg_per_goal"]
    ]
    .round(4)
    .to_string(index=False)
)
print()
print(calibration_by_season.round(3).to_string(index=False))
print()
print(strength_rates.round(3).to_string(index=False))
print()
print(state_rates.sort_values("shots", ascending=False).round(3).to_string(index=False))
print()
print("Top shooters by xG")
print(top_shooters_xg[columns["shooters"]].round(2).to_string(index=False))
print()
print("Top shooters by goals above xG")
print(top_shooters_finishing[columns["shooters"]].round(2).to_string(index=False))
print()
print("Goalies by GSAx, top and bottom 10")
print(goalie_ends[columns["goalies"]].round(3).to_string(index=False))
