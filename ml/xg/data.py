"""The xG training set: which shots, which columns, and how seasons split into folds.

The query is returned as SQL so any runner can execute it: the notebook with Spark,
a scheduled job later with the warehouse connector.
"""

from dataclasses import dataclass

import pandas as pd

FEATURE_COLUMNS = [
    "x_ft",
    "y_ft",
    "distance_ft",
    "angle_deg",
    "is_quality_chance",
    "shot_type",
    "is_rebound",
    "strength_state",
    "score_diff",
    "period",
]


def shots_query(gold_schema: str, silver_schema: str) -> str:
    """SQL for the training set: shots at a goalie, regular season and playoffs.

    Blocked shots never reach the goalie and empty-net shots always score, so neither
    belongs in the model. Preseason is left out: it's recorded differently (the 2024
    preseason has no blocked shots, and preseason goal rates run high;
    docs/plans/xg-audit.md, 1a).

    Args:
        gold_schema: Where fct_shots and fct_games live, e.g. ``dev.dbt_apetry_gold``.
        silver_schema: Where stg_pwhl__seasons lives, e.g. ``dev.dbt_apetry_silver``.
    """
    columns = ",\n    ".join(
        # A missing quality description counts as not flagged; models can't take nulls.
        f"coalesce(shots.{column}, false) as {column}"
        if column == "is_quality_chance"
        else f"shots.{column}"
        for column in FEATURE_COLUMNS
    )
    # Identifiers can't be bound as parameters. The schema names come from the
    # notebook's own widgets (trusted config) and are backtick-quoted.
    return f"""
select
    shots.season_id,
    seasons.season_name,
    shots.season_type,
    year(seasons.end_date) as season_year,
    shots.game_id,
    games.game_date,
    shots.event_index,
    shots.is_goal,
    {columns}
from {_quoted(gold_schema)}.`fct_shots` as shots
inner join {_quoted(silver_schema)}.`stg_pwhl__seasons` as seasons
    on shots.season_id = seasons.season_id
inner join {_quoted(gold_schema)}.`fct_games` as games
    on shots.game_id = games.game_id
where
    shots.is_unblocked
    and not shots.is_empty_net
    and shots.season_type in ('regular', 'playoffs')
"""  # noqa: S608


def _quoted(schema: str) -> str:
    """`dev`.`dbt_apetry_gold` from dev.dbt_apetry_gold."""
    return ".".join(f"`{part}`" for part in schema.split("."))


@dataclass(frozen=True)
class Fold:
    """One train/test split: train on earlier season years, test on the next."""

    test_year: int
    train: pd.DataFrame
    test: pd.DataFrame


def season_folds(shots: pd.DataFrame) -> list[Fold]:
    """Forward-chaining folds by season year (a regular season plus its playoffs).

    With years 2024-2026 this gives train 2024 -> test 2025, and train 2024-2025 ->
    test 2026. It mirrors real use, where a model trained on past seasons scores the
    next one, and keeps every game (and a shot and its rebound) on one side.

    Raises:
        ValueError: A shot has no season year (its season has no end date), or a game
            spans two season years, either of which would make the folds wrong.
    """
    if shots["season_year"].isna().any():
        raise ValueError("Some shots have no season_year; check seasons' end_date.")
    if (shots.groupby("game_id")["season_year"].nunique() > 1).any():
        raise ValueError("A game_id appears in more than one season_year.")
    years = sorted(shots["season_year"].unique())
    return [
        Fold(
            test_year=int(year),
            train=shots[shots["season_year"] < year],
            test=shots[shots["season_year"] == year],
        )
        for year in years[1:]
    ]
