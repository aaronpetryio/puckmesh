"""SQL for the xG predictions table: create it, stage new rows, swap them in.

One row per shot per model version in ``<catalog>.ml.xg_predictions``, declared as a
dbt source. Rows are written to a staging table in batches, then swapped in with one
``insert ... replace where``, so readers never see a half-written model version.

Identifiers can't be bound as parameters, so they're formatted in (``# noqa: S608``).
They come from our own config; the values are numbers, our model version, and a league
id checked against a short pattern.
"""

import re

import pandas as pd

SCHEMA = "ml"
TABLE = "xg_predictions"
STAGING_TABLE = "xg_predictions_staging"

_COLUMNS = """
    league_id string comment 'League the shot is from, e.g. pwhl',
    game_id int comment 'fct_shots.game_id',
    event_index int comment 'fct_shots.event_index',
    season_year int comment 'Year the season ends',
    model_version string comment 'Model definition, e.g. v1.1 (ml/xg/model.py)',
    xg_raw double comment 'Model probability of a goal, before rescaling',
    xg double comment 'xg_raw rescaled so the season total tracks goals to date',
    scored_at timestamp comment 'When this row was written'
"""
_LEAGUE_ID = re.compile(r"^[a-z0-9_]+$")
_MODEL_VERSION = re.compile(r"^v[0-9.]+$")


def table(catalog: str, name: str = TABLE) -> str:
    """`dev`.`ml`.`xg_predictions` for catalog dev."""
    return f"`{catalog}`.`{SCHEMA}`.`{name}`"


def create_statements(catalog: str) -> list[str]:
    """Create the ml schema and the predictions table, if they're missing."""
    return [
        f"create schema if not exists `{catalog}`.`{SCHEMA}`",
        f"""
create table if not exists {table(catalog)} ({_COLUMNS})
comment 'xG per shot per model version. Written only by python -m ml.xg.'
""",
    ]


def create_staging_statement(catalog: str) -> str:
    return f"create or replace table {table(catalog, STAGING_TABLE)} ({_COLUMNS})"


def drop_staging_statement(catalog: str) -> str:
    return f"drop table if exists {table(catalog, STAGING_TABLE)}"


def insert_statements(
    catalog: str,
    predictions: pd.DataFrame,
    model_version: str,
    batch_size: int = 1000,
) -> list[str]:
    """Insert into the staging table, ``batch_size`` rows per statement.

    ``predictions`` has league_id, game_id, event_index, season_year, xg_raw and xg.
    """
    _check_version(model_version)
    if not predictions["league_id"].map(lambda v: bool(_LEAGUE_ID.match(v))).all():
        raise ValueError("Unexpected league_id; expected lowercase letters and digits.")
    rows = [
        f"('{row.league_id}', {int(row.game_id)}, {int(row.event_index)}, "
        f"{int(row.season_year)}, '{model_version}', {float(row.xg_raw)!r}, "
        f"{float(row.xg)!r}, current_timestamp())"
        for row in predictions.itertuples(index=False)
    ]
    return [
        f"insert into {table(catalog, STAGING_TABLE)} values\n"
        + ",\n".join(rows[start : start + batch_size])
        for start in range(0, len(rows), batch_size)
    ]


def replace_statement(catalog: str, model_version: str, season_years: list[int]) -> str:
    """Swap the staged rows in for these seasons of this model version, atomically."""
    _check_version(model_version)
    years = ", ".join(str(int(year)) for year in season_years)
    return f"""
insert into {table(catalog)}
replace where model_version = '{model_version}' and season_year in ({years})
select * from {table(catalog, STAGING_TABLE)}
"""  # noqa: S608


def _check_version(model_version: str) -> None:
    # It also comes back from a registered model's tag, so check it before using it.
    if not _MODEL_VERSION.match(model_version):
        raise ValueError(f"Unexpected model version {model_version!r}; expected v1.1.")
