"""xG model v1: logistic regression on location splines plus shot context.

Features are added one at a time and kept only if they help on held-out seasons
(``forward_select``). Gradient boosting is fit on the same features as a comparison.
See docs/plans/xg-model.md, step 4.
"""

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import (
    FunctionTransformer,
    OneHotEncoder,
    OrdinalEncoder,
    SplineTransformer,
)

from ml.xg import metrics
from ml.xg.data import Fold

CATEGORICAL = ["shot_type", "strength", "period_group"]

# Candidates for forward selection, in the order they're tried.
FEATURE_STEPS = [
    "shot_type",
    "is_rebound",
    "strength",
    "score_diff_capped",
    "period_group",
]


def add_features(shots: pd.DataFrame) -> pd.DataFrame:
    """Model-ready columns derived from the training set's raw ones.

    - ``log_distance``: goal rate falls fastest close to the net, which a log scale
      spreads out for the spline.
    - ``strength``: advantage, even or shorthanded, from ``strength_state`` (``5v4``
      for/against). The full state has too few shots in most cells (e.g. 74 at 5v3).
    - ``score_diff_capped``: capped at +/-3, since larger leads are rare.
    - ``period_group``: 1, 2, 3 or OT; overtime periods are few and alike.
    """
    skaters = shots["strength_state"].str.split("v", expand=True).astype(int)
    return shots.assign(
        log_distance=np.log1p(shots["distance_ft"]),
        strength=np.select(
            [skaters[0] > skaters[1], skaters[0] < skaters[1]],
            ["advantage", "shorthanded"],
            "even",
        ),
        score_diff_capped=shots["score_diff"].clip(-3, 3),
        period_group=np.where(shots["period"] > 3, "OT", shots["period"].astype(str)),
    )


def fit_logistic(
    train: pd.DataFrame,
    features: list[str],
    *,
    distance: str = "log_distance",
    distance_knots: int = 4,
) -> Pipeline:
    """Logistic regression on splines of distance and angle, plus ``features``.

    Categorical features are one-hot encoded; the rest go in as numbers. The returned
    pipeline is fitted on only the columns it uses; score shots with ``predict``.
    """
    transformers = [
        ("distance", SplineTransformer(n_knots=distance_knots), [distance]),
        ("angle", SplineTransformer(n_knots=5), ["angle_deg"]),
    ]
    categorical = [f for f in features if f in CATEGORICAL]
    numeric = [f for f in features if f not in CATEGORICAL]
    if categorical:
        transformers.append(
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical)
        )
    if numeric:
        transformers.append(("numeric", _as_float(), numeric))
    model = make_pipeline(
        ColumnTransformer(transformers), LogisticRegression(max_iter=2000)
    )
    columns = [distance, "angle_deg", *features]
    return model.fit(train[columns], train["is_goal"].astype(int))


def fit_gradient_boosting(train: pd.DataFrame, features: list[str]) -> Pipeline:
    """HistGradientBoosting on raw distance and angle plus ``features``.

    Settings are deliberately cautious (few leaves, strong L2, early stopping): with
    ~1k goals per fold, larger trees fit noise.
    """
    categorical = [f for f in features if f in CATEGORICAL]
    numeric = [
        "distance_ft",
        "angle_deg",
        *(f for f in features if f not in CATEGORICAL),
    ]
    encode = ColumnTransformer(
        [
            (
                "categorical",
                # Unseen categories become missing, which the trees handle.
                OrdinalEncoder(
                    handle_unknown="use_encoded_value", unknown_value=np.nan
                ),
                categorical,
            ),
            ("numeric", _as_float(), numeric),
        ]
    )
    boost = HistGradientBoostingClassifier(
        learning_rate=0.03,
        max_leaf_nodes=7,
        l2_regularization=10.0,
        min_samples_leaf=50,
        categorical_features=[True] * len(categorical) + [False] * len(numeric),
        early_stopping=True,
        validation_fraction=0.2,
        random_state=0,
    )
    model = make_pipeline(encode, boost)
    return model.fit(train[categorical + numeric], train["is_goal"].astype(int))


def predict(model: Pipeline, shots: pd.DataFrame) -> np.ndarray:
    """P(goal) for each shot; extra columns in ``shots`` are ignored."""
    return model.predict_proba(shots[model.feature_names_in_])[:, 1]


def forward_select(
    folds: list[Fold], candidates: list[str]
) -> tuple[list[str], pd.DataFrame]:
    """Add candidates one at a time; keep one only if log loss drops in every fold.

    Pass validation folds only, not the season the model is reported on: choosing
    on the test season flatters its score. Returns the kept features and one row
    per (step, test year).
    """
    kept: list[str] = []
    rows = []
    best = _fold_scores(folds, kept)
    rows += _rows("location only", kept, best, is_kept=True)
    for candidate in candidates:
        trial = _fold_scores(folds, [*kept, candidate])
        is_kept = all(
            trial[year]["log_loss"] < best[year]["log_loss"] for year in trial
        )
        rows += _rows(f"+ {candidate}", [*kept, candidate], trial, is_kept=is_kept)
        if is_kept:
            kept, best = [*kept, candidate], trial
    return kept, pd.DataFrame(rows)


def rescale_to_date(
    shots: pd.DataFrame, xg: np.ndarray, prior_goals: float = 50
) -> np.ndarray:
    """Shift each shot's xG so the season's xG total tracks its goals so far.

    Each game day's factor comes only from earlier days in the same season year, so
    it never uses the result it's adjusting. ``prior_goals`` pseudo-goals (at a
    factor of 1) keep the first few days from swinging it. The shift is applied on
    the log-odds scale, which keeps every xG between 0 and 1.
    """
    frame = shots[["season_year", "game_date", "is_goal"]].assign(xg=xg)
    days = (
        frame.groupby(["season_year", "game_date"])
        .agg(goals=("is_goal", "sum"), xg=("xg", "sum"))
        .sort_index()
    )
    by_season = days.groupby(level="season_year")
    goals_before = by_season["goals"].cumsum() - days["goals"]
    xg_before = by_season["xg"].cumsum() - days["xg"]
    factor = (goals_before + prior_goals) / (xg_before + prior_goals)
    shift = np.log(
        frame.join(factor.rename("factor"), on=["season_year", "game_date"])["factor"]
    )
    return expit(logit(xg) + shift.to_numpy())


def _fold_scores(folds: list[Fold], features: list[str]) -> dict[int, dict]:
    return {
        fold.test_year: metrics.score(
            fold.test["is_goal"], predict(fit_logistic(fold.train, features), fold.test)
        )
        for fold in folds
    }


def _rows(step: str, features: list[str], scores: dict, *, is_kept: bool) -> list[dict]:
    return [
        {"step": step, "features": ", ".join(features), "is_kept": is_kept}
        | {"test_year": year}
        | score
        for year, score in scores.items()
    ]


def _as_float() -> FunctionTransformer:
    # Booleans and integers in as floats. np.asarray, not a lambda, so the fitted
    # pipeline can be pickled for MLflow.
    return FunctionTransformer(np.asarray, kw_args={"dtype": float})
