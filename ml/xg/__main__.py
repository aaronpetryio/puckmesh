"""Command line for publishing xG: train and register a model, score shots, write them.

Usage:
    python -m ml.xg setup --target dev|prod      (create ml schema and table if missing)
    python -m ml.xg train --target dev|prod --through-season 2026
    python -m ml.xg score --target dev|prod      (what the scheduled job runs)

``train`` is run by hand once a season ends: it writes out-of-fold xG for every
completed season and registers a model fit on all of them. ``score`` loads that
registered model and scores the seasons after it (the current one). Nothing here
refits during scoring, so published xG always comes from a reviewed model.

This is the only part of ml/ that reaches the warehouse or MLflow. The SQL and the
modeling come from data.py, model.py and publish.py. See docs/plans/xg-model.md,
steps 6 and 7.
"""

import argparse
import os

import mlflow
import mlflow.sklearn
import pandas as pd
from databricks.sql.client import Cursor
from dotenv import load_dotenv
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from extract import db
from ml.xg import data, metrics, model, publish

EXPERIMENT = "/Shared/puckmesh-xg"
ALIAS = "champion"


def _schemas(target: str) -> tuple[str, str, str]:
    """Catalog, gold schema and silver schema for a dbt target, as dbt names them."""
    if target == "prod":
        return "prod", "prod.gold", "prod.silver"
    prefix = db.dbt_schema()
    return "dev", f"dev.{prefix}_gold", f"dev.{prefix}_silver"


def _registered_name(catalog: str) -> str:
    return f"{catalog}.{publish.SCHEMA}.xg_model"


def _use_databricks_mlflow() -> None:
    # Reads DATABRICKS_HOST and DATABRICKS_TOKEN from the environment; models are
    # registered in Unity Catalog, next to the predictions table.
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")


def _read_shots(cur: Cursor, gold: str, silver: str) -> pd.DataFrame:
    cur.execute(data.shots_query(gold, silver))
    columns = [column[0] for column in cur.description]
    return model.add_features(
        pd.DataFrame.from_records(cur.fetchall(), columns=columns)
    )


def _write(
    cur: Cursor, catalog: str, predictions: pd.DataFrame, model_version: str
) -> None:
    """Stage the rows, then swap them in for their seasons in one statement."""
    cur.execute(publish.create_staging_statement(catalog))
    for statement in publish.insert_statements(catalog, predictions, model_version):
        cur.execute(statement)
    years = sorted(predictions["season_year"].unique())
    cur.execute(publish.replace_statement(catalog, model_version, years))
    cur.execute(publish.drop_staging_statement(catalog))


def _summary(predictions: pd.DataFrame, shots: pd.DataFrame) -> str:
    goals = shots.groupby("season_year")["is_goal"].sum().rename("goals")
    totals = (
        predictions.groupby("season_year")
        .agg(shots=("xg", "size"), xg_raw=("xg_raw", "sum"), xg=("xg", "sum"))
        .join(goals)
        .round(1)
    )
    return totals.to_string()


def cmd_setup(cur: Cursor, catalog: str) -> None:
    for statement in publish.create_statements(catalog):
        cur.execute(statement)
    print(f"{publish.table(catalog)} is ready.")


def cmd_train(cur: Cursor, target: str, through_season: int) -> None:
    catalog, gold, silver = _schemas(target)
    cmd_setup(cur, catalog)
    shots = _read_shots(cur, gold, silver)
    completed = shots[shots["season_year"] <= through_season]
    predictions = model.backfill(shots, model.V1_FEATURES, through_season)

    _use_databricks_mlflow()
    mlflow.set_experiment(EXPERIMENT)
    name = _registered_name(catalog)
    with mlflow.start_run(run_name=f"train {model.MODEL_VERSION} {target}"):
        mlflow.log_params(
            {
                "target": target,
                "model_version": model.MODEL_VERSION,
                "features": ", ".join(model.V1_FEATURES),
                "through_season": through_season,
            }
        )
        # Out-of-fold scores of what's being published, per season.
        for year, season in predictions.groupby("season_year"):
            is_goal = completed.loc[season.index, "is_goal"]
            score = metrics.score(is_goal, season["xg"].to_numpy())
            mlflow.log_metrics(
                {
                    f"{metric}_{year}": score[metric]
                    for metric in ("log_loss", "auc", "xg_per_goal")
                }
            )
        fitted = model.fit_logistic(completed, model.V1_FEATURES)
        # Cloudpickle, as in notebooks/xg_model_v1.py: skops rejects the spline's types.
        info = mlflow.sklearn.log_model(
            fitted,
            name="model",
            input_example=completed.head(5)[fitted.feature_names_in_],
            registered_model_name=name,
            serialization_format="cloudpickle",
        )
    client = MlflowClient()
    version = info.registered_model_version
    client.set_model_version_tag(name, version, "model_version", model.MODEL_VERSION)
    client.set_model_version_tag(name, version, "through_season", str(through_season))
    # Written before the alias moves, so scoring never sees a model without its xG.
    _write(cur, catalog, predictions, model.MODEL_VERSION)
    client.set_registered_model_alias(name, ALIAS, version)
    print(f"Registered {name} version {version} as @{ALIAS}.")
    print(_summary(predictions, completed))


def cmd_score(cur: Cursor, target: str) -> None:
    catalog, gold, silver = _schemas(target)
    cmd_setup(cur, catalog)
    _use_databricks_mlflow()
    name = _registered_name(catalog)
    try:
        registered = MlflowClient().get_model_version_by_alias(name, ALIAS)
    except MlflowException:
        # Until the first training run; not a failure of the daily pipeline.
        message = f"No {name}@{ALIAS} yet; run python -m ml.xg train. Nothing scored."
        print(f"::warning::{message}" if os.environ.get("GITHUB_ACTIONS") else message)
        return
    through_season = int(registered.tags["through_season"])
    model_version = registered.tags["model_version"]
    fitted = mlflow.sklearn.load_model(f"models:/{name}@{ALIAS}")
    shots = _read_shots(cur, gold, silver)
    predictions = model.score_new(shots, fitted, through_season)
    if predictions.empty:
        print(f"No shots after season {through_season} yet. Nothing to score.")
        return
    _write(cur, catalog, predictions, model_version)
    print(f"Scored with {name} version {registered.version} ({model_version}).")
    print(_summary(predictions, shots.loc[predictions.index]))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m ml.xg")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("setup", "train", "score"):
        sub = commands.add_parser(command)
        sub.add_argument("--target", choices=["dev", "prod"], default="dev")
        if command == "train":
            sub.add_argument("--through-season", type=int, required=True)
    args = parser.parse_args()

    with db.connect() as conn, conn.cursor() as cur:
        if args.command == "setup":
            cmd_setup(cur, _schemas(args.target)[0])
        elif args.command == "train":
            cmd_train(cur, args.target, args.through_season)
        else:
            cmd_score(cur, args.target)


if __name__ == "__main__":
    main()
