"""Sanity-check tables for an xG model: by player, and by any shot column.

Each takes shots (the training set's columns) and one xG value per shot. See
docs/plans/xg-model.md, step 5.
"""

import numpy as np
import pandas as pd


def shooter_table(
    shots: pd.DataFrame, xg: np.ndarray, min_shots: int, *, by_season: bool = False
) -> pd.DataFrame:
    """Goals vs xG per shooter, over all seasons or per season year.

    ``goals_above_xg`` is goals minus xG: finishing better (or luckier) than the
    model's average shooter from the same spots.
    """
    table = _totals(shots, xg, "shooter_player_id", min_shots, by_season=by_season)
    return table.rename(columns={"shooter_player_id": "player_id"}).assign(
        goals_above_xg=lambda df: df["goals"] - df["xg"],
        shooting_pct=lambda df: df["goals"] / df["shots"],
        xg_per_shot=lambda df: df["xg"] / df["shots"],
    )


def goalie_table(
    shots: pd.DataFrame, xg: np.ndarray, min_shots: int, *, by_season: bool = False
) -> pd.DataFrame:
    """Goals saved above expected (GSAx) per goalie, over all seasons or per season.

    GSAx is xG against minus goals against: positive means fewer goals allowed than
    the shots faced would predict. Shots with no goalie recorded are dropped.
    """
    table = _totals(shots, xg, "goalie_player_id", min_shots, by_season=by_season)
    return table.rename(
        columns={
            "goalie_player_id": "player_id",
            "shots": "shots_against",
            "goals": "goals_against",
            "xg": "xg_against",
        }
    ).assign(
        gsax=lambda df: df["xg_against"] - df["goals_against"],
        save_pct=lambda df: 1 - df["goals_against"] / df["shots_against"],
        expected_save_pct=lambda df: 1 - df["xg_against"] / df["shots_against"],
    )


def rates_by(shots: pd.DataFrame, xg: np.ndarray, column: str) -> pd.DataFrame:
    """Actual vs predicted goal rate for each value of ``column``."""
    return (
        _frame(shots, xg)
        .groupby(column, observed=True)
        .agg(shots=("is_goal", "size"), goals=("is_goal", "sum"), xg=("xg", "sum"))
        .assign(
            actual_rate=lambda df: df["goals"] / df["shots"],
            predicted_rate=lambda df: df["xg"] / df["shots"],
            xg_per_goal=lambda df: df["xg"] / df["goals"],
        )
        .reset_index()
    )


def _frame(shots: pd.DataFrame, xg: np.ndarray) -> pd.DataFrame:
    return shots.assign(is_goal=shots["is_goal"].astype(int), xg=xg)


def _totals(
    shots: pd.DataFrame,
    xg: np.ndarray,
    player_column: str,
    min_shots: int,
    *,
    by_season: bool,
) -> pd.DataFrame:
    keys = [player_column, "season_year"] if by_season else [player_column]
    frame = _frame(shots, xg).dropna(subset=[player_column])
    return (
        frame.groupby(keys)
        .agg(shots=("is_goal", "size"), goals=("is_goal", "sum"), xg=("xg", "sum"))
        .loc[lambda df: df["shots"] >= min_shots]
        .reset_index()
    )
