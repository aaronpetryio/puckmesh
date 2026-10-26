from extract.state import State


def test_partitions_match_regardless_of_order():
    state = State()
    state.record("roster", {"team_id": 4, "season_id": 8}, "abc")
    assert state.latest_hash("roster", {"season_id": 8, "team_id": 4}) == "abc"
    assert state.has("roster", {"season_id": 8, "team_id": 4})


def test_partitions_are_distinct():
    state = State()
    state.record("play_by_play", {"season_id": 8, "game_id": 1}, "abc")
    assert not state.has("play_by_play", {"season_id": 8, "game_id": 2})
    assert not state.has("roster", {"season_id": 8, "game_id": 1})
    assert state.latest_hash("play_by_play", {"season_id": 8}) is None
