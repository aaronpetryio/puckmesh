"""Tests for ml.xg: folds, baselines and metrics on synthetic shots."""

import numpy as np
import pandas as pd
import pytest

from ml.xg import baselines, data, metrics


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
