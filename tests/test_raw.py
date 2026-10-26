import json

from extract import raw
from extract.state import State


def test_content_hash_ignores_key_order():
    assert raw.content_hash({"a": 1, "b": 2}) == raw.content_hash({"b": 2, "a": 1})


def test_content_hash_treats_empty_list_and_dict_alike():
    assert raw.content_hash({"x": []}) == raw.content_hash({"x": {}})
    assert raw.content_hash({"x": [{"y": []}]}) == raw.content_hash({"x": [{"y": {}}]})


def test_content_hash_changes_with_content():
    assert raw.content_hash({"a": 1}) != raw.content_hash({"a": 2})


def test_save_writes_envelope_in_partition_folders(raw_root):
    state = State()
    params = {"feed": "modulekit", "view": "roster", "key": "k", "fmt": "json"}
    path = raw.save("pwhl", "roster", {"r": 1}, params, state, season_id=8, team_id=4)

    assert path.parent == raw_root / "pwhl" / "roster" / "season_id=8" / "team_id=4"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    meta = envelope["_meta"]
    assert envelope["response"] == {"r": 1}
    assert meta["season_id"] == 8
    assert meta["team_id"] == 4
    assert meta["params"] == {"feed": "modulekit", "view": "roster"}
    assert meta["content_hash"] == raw.content_hash({"r": 1})
    assert ":" not in path.name


def test_save_skips_unchanged_content(raw_root):
    state = State()
    assert raw.save("pwhl", "seasons", {"s": 1}, {}, state) is not None
    assert raw.save("pwhl", "seasons", {"s": 1}, {}, state) is None
    assert raw.save("pwhl", "seasons", {"s": 2}, {}, state) is not None
    assert len(list((raw_root / "pwhl" / "seasons").iterdir())) == 2
