"""Baselines a real xG model has to beat, from no information to distance and angle.

Each function fits on the train shots and returns P(goal) for the test shots.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer

Baseline = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]


def league_average(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Every shot gets the train goal rate: the score of knowing nothing about it."""
    return np.full(len(test), train["is_goal"].mean())


def quality_flag(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """The league's own quality-chance zone, as a benchmark (not a model feature)."""
    return _fit_predict(train, test, ["is_quality_chance"], splines=False)


def distance(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Logistic regression on a smooth curve (spline) of distance to the net."""
    return _fit_predict(train, test, ["distance_ft"], splines=True)


def distance_angle(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Logistic regression on splines of distance and angle (~ the 18 Skaters model)."""
    return _fit_predict(train, test, ["distance_ft", "angle_deg"], splines=True)


BASELINES: dict[str, Baseline] = {
    "league_average": league_average,
    "quality_flag": quality_flag,
    "distance": distance,
    "distance_angle": distance_angle,
}


def _fit_predict(
    train: pd.DataFrame, test: pd.DataFrame, columns: list[str], *, splines: bool
) -> np.ndarray:
    # Splines let the goal rate fall steeply near the net and flatten far out, which a
    # straight line on distance can't. Five knots is enough for ~10k shots per fold.
    steps = [SplineTransformer(n_knots=5, degree=3)] if splines else []
    model = make_pipeline(*steps, LogisticRegression(max_iter=1000))
    model.fit(train[columns].astype(float), train["is_goal"].astype(int))
    return model.predict_proba(test[columns].astype(float))[:, 1]
