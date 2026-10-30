"""Tests for ml.xg: folds, baselines, models, metrics and evaluation tables."""

import numpy as np
import pandas as pd
import pytest

from ml.xg import baselines, data, evaluate, metrics, model


def make_shots(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    distance = rng.uniform(3, 80, n)
    # Closer shots score more often, as in the real data.
    is_goal = rng.random(n) < 0.25 * np.exp(-distance / 20)
    return pd.DataFrame(
        {
            "season_year": np.repeat([2024, 2025, 2026], n // 3),
            "game_id": np.repeat(np.arange(n // 20), 20),
            "is_goal": is_goal,
            "distance_ft": distance,
            "angle_deg": rng.uniform(0, 90, n),
            "is_quality_chance": distance < 30,
        }
    )


def test_folds_chain_forward_without_sharing_games():
    folds = data.season_folds(make_shots())
    assert [fold.test_year for fold in folds] == [2025, 2026]
    for fold in folds:
        assert fold.train["season_year"].max() < fold.test_year
        assert set(fold.train["game_id"]).isdisjoint(fold.test["game_id"])
    assert set(folds[1].train["season_year"]) == {2024, 2025}


def test_folds_reject_a_game_in_two_season_years():
    shots = make_shots()
    shots.loc[0, "game_id"] = shots["game_id"].max()
    with pytest.raises(ValueError, match="more than one season_year"):
        data.season_folds(shots)


def test_league_average_is_the_train_rate():
    shots = make_shots()
    xg = baselines.league_average(shots.iloc[:400], shots.iloc[400:])
    assert len(xg) == 200
    assert np.allclose(xg, shots.iloc[:400]["is_goal"].mean())


@pytest.mark.parametrize("name", ["quality_flag", "distance", "distance_angle"])
def test_baselines_return_probabilities(name):
    shots = make_shots()
    xg = baselines.BASELINES[name](shots.iloc[:400], shots.iloc[400:])
    assert len(xg) == 200
    assert ((xg > 0) & (xg < 1)).all()


def test_distance_baseline_favors_close_shots():
    shots = make_shots(n=3000)
    test = pd.DataFrame({"distance_ft": [5.0, 60.0]})
    xg = baselines.distance(shots, test)
    assert xg[0] > xg[1]


def test_score_matches_hand_computed_values():
    result = metrics.score(pd.Series([True, False]), np.array([0.5, 0.5]))
    assert result["shots"] == 2
    assert result["goals"] == 1
    assert result["log_loss"] == pytest.approx(np.log(2))
    assert result["brier"] == pytest.approx(0.25)
    assert result["auc"] == pytest.approx(0.5)
    assert result["xg_per_goal"] == pytest.approx(1.0)


def test_calibration_by_distance_bands_shots():
    shots = pd.DataFrame(
        {"distance_ft": [5.0, 15.0, 15.0, 75.0], "is_goal": [True, False, True, False]}
    )
    table = metrics.calibration_by_distance(shots, np.array([0.4, 0.1, 0.3, 0.02]))
    ten_to_twenty = table[table["band"] == "10-20 ft"].iloc[0]
    assert ten_to_twenty["shots"] == 2
    assert ten_to_twenty["actual_rate"] == pytest.approx(0.5)
    assert ten_to_twenty["predicted_rate"] == pytest.approx(0.2)
    assert table["shots"].sum() == 4


def test_shots_query_filters_and_uses_schemas():
    sql = data.shots_query("dev.gold", "dev.silver")
    assert "from `dev`.`gold`.`fct_shots`" in sql
    assert "`dev`.`silver`.`stg_pwhl__seasons`" in sql
    assert "shots.is_unblocked" in sql
    assert "not shots.is_empty_net" in sql
    assert "('regular', 'playoffs')" in sql
    assert "`dev`.`gold`.`fct_games`" in sql
    assert "shots.shooter_player_id" in sql
    assert "shots.goalie_player_id" in sql


def test_players_query_uses_schema():
    assert "from `dev`.`gold`.`dim_players`" in data.players_query("dev.gold")


def make_model_shots(n: int = 3000, seed: int = 0) -> pd.DataFrame:
    """Shots where distance and rebounds drive goals.

    ``misleading`` matches goals in 2024 and runs the other way after, so a model
    trained on 2024 and tested on 2025 is hurt by it.
    """
    rng = np.random.default_rng(seed)
    shots = make_shots(n=n, seed=seed)
    is_rebound = rng.random(n) < 0.1
    rate = 0.25 * np.exp(-shots["distance_ft"] / 20) * np.where(is_rebound, 3, 1)
    is_goal = rng.random(n) < rate
    return model.add_features(
        shots.assign(
            is_goal=is_goal,
            misleading=np.where(shots["season_year"] == 2024, is_goal, ~is_goal),
            is_rebound=is_rebound,
            shot_type=rng.choice(["Wrist", "Tip", "Default"], n),
            strength_state=rng.choice(["5v5", "5v4", "4v5"], n),
            score_diff=rng.integers(-5, 6, n),
            period=rng.integers(1, 5, n),
        )
    )


def test_add_features_maps_strength_and_caps():
    shots = pd.DataFrame(
        {
            "distance_ft": [0.0, 10.0, 10.0, 10.0, 10.0],
            "strength_state": ["5v5", "5v4", "4v5", "6v5", "3v3"],
            "score_diff": [-5, 0, 2, 4, 0],
            "period": [1, 2, 3, 4, 5],
        }
    )
    features = model.add_features(shots)
    assert features["strength"].tolist() == [
        "even",
        "advantage",
        "shorthanded",
        "advantage",
        "even",
    ]
    assert features["is_3v3"].tolist() == [False, False, False, False, True]
    assert features["score_diff_capped"].tolist() == [-3, 0, 2, 3, 0]
    assert features["period_group"].tolist() == ["1", "2", "3", "OT", "OT"]
    assert features["log_distance"].iloc[0] == 0


def test_forward_select_keeps_signal_and_drops_what_hurts():
    # The first fold only (train 2024, test 2025), as the notebook selects on it.
    folds = data.season_folds(make_model_shots())[:1]
    kept, results = model.forward_select(folds, ["is_rebound", "misleading"])
    assert kept == ["is_rebound"]
    assert set(results["step"]) == {"location only", "+ is_rebound", "+ misleading"}
    assert len(results) == 3


def test_models_score_with_extra_columns():
    shots = make_model_shots()
    features = ["shot_type", "is_rebound", "strength"]
    for fit in (model.fit_logistic, model.fit_gradient_boosting):
        fitted = fit(shots.iloc[:2000], features)
        xg = model.predict(fitted, shots.iloc[2000:])
        assert len(xg) == 1000
        assert ((xg > 0) & (xg < 1)).all()


def test_rescale_uses_only_earlier_days():
    shots = pd.DataFrame(
        {
            "season_year": [2026] * 4,
            "game_date": pd.to_datetime(["2026-01-01"] * 2 + ["2026-01-02"] * 2),
            "is_goal": [True, True, False, False],
        }
    )
    xg = np.full(4, 0.1)
    rescaled = model.rescale_to_date(shots, xg, prior_goals=0.1)
    # Day one has nothing earlier to learn from, so it's unchanged.
    assert rescaled[:2] == pytest.approx([0.1, 0.1])
    # Day two sees 2 goals on 0.2 xG the day before: a factor of (2 + 0.1) / (0.2 +
    # 0.1) = 7 on the odds, so 0.1 (odds 1/9) becomes odds 7/9, or 0.4375.
    assert rescaled[2:] == pytest.approx([0.4375, 0.4375])


def test_rescale_brings_totals_toward_goals():
    rng = np.random.default_rng(0)
    n = 4000
    shots = pd.DataFrame(
        {
            "season_year": 2026,
            "game_date": pd.to_datetime("2026-01-01")
            + pd.to_timedelta(np.repeat(np.arange(100), n // 100), unit="D"),
            "is_goal": rng.random(n) < 0.06,
        }
    )
    xg = np.full(n, 0.09)  # The model thinks shots score half again too often.
    rescaled = model.rescale_to_date(shots, xg)
    goals = shots["is_goal"].sum()
    assert abs(rescaled.sum() / goals - 1) < abs(xg.sum() / goals - 1) / 3


def test_out_of_fold_scores_each_season_without_it():
    shots = make_model_shots()
    xg = model.out_of_fold(shots, model.V1_FEATURES)
    assert len(xg) == len(shots)
    assert ((xg > 0) & (xg < 1)).all()
    # 2024's xG matches a model fit on 2025-2026 only.
    is_2024 = shots["season_year"] == 2024
    fitted = model.fit_logistic(shots[~is_2024], model.V1_FEATURES)
    assert xg[is_2024] == pytest.approx(model.predict(fitted, shots[is_2024]))


def test_out_of_fold_rejects_a_shot_without_a_season():
    shots = make_model_shots()
    shots.loc[0, "season_year"] = np.nan
    with pytest.raises(ValueError, match="no season_year"):
        model.out_of_fold(shots, model.V1_FEATURES)


def make_player_shots() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season_year": [2025, 2025, 2025, 2026, 2026, 2026],
            "shooter_player_id": [1, 1, 2, 1, 2, 2],
            "goalie_player_id": [9, 9, 9, 9, 8, np.nan],
            "is_goal": [True, False, False, True, True, False],
            "strength": ["even"] * 4 + ["advantage"] * 2,
        }
    )


def test_shooter_table_totals_and_filter():
    shots = make_player_shots()
    xg = np.full(6, 0.25)
    table = evaluate.shooter_table(shots, xg, min_shots=3).set_index("player_id")
    assert table.loc[1, ["shots", "goals"]].tolist() == [3, 2]
    assert table.loc[1, "goals_above_xg"] == pytest.approx(1.25)
    by_season = evaluate.shooter_table(shots, xg, min_shots=2, by_season=True)
    # Player 1 has 1 shot in 2026 and player 2 has 1 in 2025: both filtered out.
    assert set(zip(by_season["player_id"], by_season["season_year"], strict=True)) == {
        (1, 2025),
        (2, 2026),
    }


def test_goalie_table_gsax_drops_shots_without_a_goalie():
    shots = make_player_shots()
    xg = np.full(6, 0.25)
    table = evaluate.goalie_table(shots, xg, min_shots=1).set_index("player_id")
    assert table["shots_against"].sum() == 5
    # Goalie 9: 2 goals on 1.0 xG, so 1 goal worse than expected.
    assert table.loc[9, "gsax"] == pytest.approx(-1.0)
    assert table.loc[9, "save_pct"] == pytest.approx(0.5)
    assert table.loc[9, "expected_save_pct"] == pytest.approx(0.75)


def test_rates_by_column():
    shots = make_player_shots()
    rates = evaluate.rates_by(shots, np.full(6, 0.25), "strength").set_index("strength")
    assert rates.loc["even", ["shots", "goals"]].tolist() == [4, 2]
    assert rates.loc["advantage", "actual_rate"] == pytest.approx(0.5)
    assert rates.loc["advantage", "xg_per_goal"] == pytest.approx(0.5)
