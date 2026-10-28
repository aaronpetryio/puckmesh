"""How good an xG model's probabilities are.

Log loss and Brier score come first because xG is a probability: they reward being
right about how likely a goal was, not just ranking shots. AUC only checks the ranking.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

DISTANCE_BANDS = [0, 10, 20, 30, 45, 70, np.inf]
DISTANCE_LABELS = ["0-10 ft", "10-20 ft", "20-30 ft", "30-45 ft", "45-70 ft", "70+ ft"]


def score(is_goal: pd.Series, xg: np.ndarray) -> dict[str, float]:
    """Summary metrics for one model on one test set.

    ``xg_per_goal`` is total xG over actual goals: 1.0 means the model predicts the
    right number of goals overall.
    """
    y = is_goal.astype(int).to_numpy()
    return {
        "shots": len(y),
        "goals": int(y.sum()),
        "log_loss": log_loss(y, xg, labels=[0, 1]),
        "brier": brier_score_loss(y, xg),
        # AUC is undefined when the test set holds only goals or only saves.
        "auc": roc_auc_score(y, xg) if 0 < y.sum() < len(y) else np.nan,
        "xg_per_goal": xg.sum() / y.sum() if y.sum() else np.nan,
    }


def calibration_by_distance(shots: pd.DataFrame, xg: np.ndarray) -> pd.DataFrame:
    """Actual vs predicted goal rate per distance band."""
    bands = pd.cut(
        shots["distance_ft"], DISTANCE_BANDS, labels=DISTANCE_LABELS, right=False
    )
    return (
        pd.DataFrame({"band": bands, "is_goal": shots["is_goal"].astype(int), "xg": xg})
        .groupby("band", observed=False)
        .agg(shots=("is_goal", "size"), goals=("is_goal", "sum"), xg=("xg", "sum"))
        .assign(
            actual_rate=lambda df: df["goals"] / df["shots"],
            predicted_rate=lambda df: df["xg"] / df["shots"],
        )
        .reset_index()
    )
