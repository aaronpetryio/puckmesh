import json

from extract import load


class FakeCursor:
    def __init__(self, missing):
        self.missing = missing
        self.executed = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.startswith("show tables"):
            self._rows = [type("Row", (), {"tableName": "seasons"})]
        elif sql.startswith("describe table"):
            self._rows = [type("Row", (), {"col_name": "content_hash"})]
        elif sql.startswith("select source_file"):
            self._rows = [type("Row", (), {"source_file": f}) for f in self.missing]

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


def test_backfill_hashes_binds_values(raw_root, monkeypatch):
    # A file name with a quote would have broken the old string-built MERGE.
    name = "20240101T000000000000Z's.json"
    local = raw_root / "pwhl" / "seasons" / name
    local.parent.mkdir(parents=True)
    local.write_text(json.dumps({"_meta": {}, "response": {"s": 1}}), encoding="utf-8")
    remote = f"/Volumes/raw/pwhl/landing/seasons/{name}"

    cursor = FakeCursor(missing=[remote])
    monkeypatch.setattr(load.db, "connect", lambda: FakeConnection(cursor))

    assert load.backfill_hashes("pwhl") == {"seasons": 1}
    merge_sql, params = cursor.executed[-1]
    assert "merge into" in merge_sql
    assert "(:file_0, :hash_0)" in merge_sql
    assert name not in merge_sql
    assert params == {"file_0": remote, "hash_0": load.content_hash({"s": 1})}
