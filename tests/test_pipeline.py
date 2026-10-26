from datetime import date

import pytest

from extract import pipeline
from extract.state import State

SEASON = {"start_date": "2025-11-20", "end_date": "2026-05-01"}


@pytest.mark.parametrize(
    ("today", "active"),
    [
        (date(2025, 10, 20), False),  # 31 days before the start
        (date(2025, 10, 21), True),  # 30 days before
        (date(2026, 5, 15), True),  # 14 days after the end
        (date(2026, 5, 16), False),
    ],
)
def test_is_active_window(today, active):
    assert pipeline._is_active(SEASON, today) is active


class FakeClient:
    """Answers each view with canned data and records what was asked for."""

    league = "pwhl"

    def __init__(self):
        self.requests = []

    def get(self, **params):
        self.requests.append(params)
        view = params.get("view") or params.get("tab")
        if view == "seasons":
            return {
                "SiteKit": {
                    "Seasons": [
                        {
                            "season_id": "1",
                            "start_date": "2024-01-01",
                            "end_date": "2024-05-01",
                        },
                        {
                            "season_id": "2",
                            "start_date": "2025-11-20",
                            "end_date": "2026-05-01",
                        },
                    ]
                }
            }
        if view == "schedule":
            return {
                "SiteKit": {
                    "Schedule": [
                        {"game_id": "10", "final": "1", "date_played": "2026-01-01"},
                        {"game_id": "11", "final": "1", "date_played": "2026-01-09"},
                        {"game_id": "12", "final": "0", "date_played": "2026-01-20"},
                    ]
                }
            }
        if view == "teamsbyseason":
            return {"SiteKit": {"Teamsbyseason": [{"id": "1"}]}}
        if view == "roster":
            return {"SiteKit": {"Roster": []}}
        if view == "pxpverbose":
            return {"GC": {"Pxpverbose": [{"game": params["game_id"]}]}}
        raise AssertionError(params)


@pytest.fixture
def stored(raw_root, monkeypatch):
    """Game 10 of season 2 is already stored; nothing is uploaded or loaded for real."""
    state = State()
    state.record("play_by_play", {"season_id": 2, "game_id": 10}, "old")
    monkeypatch.setattr(pipeline.State, "load", classmethod(lambda cls, league: state))
    calls = []
    monkeypatch.setattr(
        pipeline, "upload", lambda league: calls.append("upload") or (0, 0)
    )
    monkeypatch.setattr(pipeline, "load", lambda league: calls.append("load") or {})
    return calls


def pbp_games(client: FakeClient) -> list[int]:
    return [r["game_id"] for r in client.requests if r.get("tab") == "pxpverbose"]


def test_daily_skips_inactive_seasons_and_old_stored_games(stored):
    client = FakeClient()
    pipeline.run(client, "daily", today=date(2026, 1, 10))

    seasons_fetched = {r.get("season_id") for r in client.requests} - {None}
    assert seasons_fetched == {2}
    # 10 is stored and not recent; 11 is new; 12 isn't final.
    assert pbp_games(client) == [11]
    assert stored == ["upload", "load"]


def test_daily_refetches_recent_stored_games(stored):
    client = FakeClient()
    pipeline.run(client, "daily", today=date(2026, 1, 3))
    assert pbp_games(client) == [10, 11]


def test_full_fetches_every_season_and_final_game(stored):
    client = FakeClient()
    pipeline.run(client, "full", today=date(2026, 1, 10))
    assert pbp_games(client) == [10, 11, 10, 11]
