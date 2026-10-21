"""What is already stored: the latest content hash per endpoint and partition.

Read from the raw tables, so it's the same answer on a laptop or a fresh CI runner.
Responses saved during this run are recorded too, so a run never saves the same
content twice even before it's been uploaded and loaded.
"""

from extract import db

# Partition keys a raw file can carry in _meta, in folder order.
PARTITION_KEYS = ("season_id", "team_id", "game_id")


def _key(endpoint: str, partitions: dict) -> tuple:
    return (endpoint,) + tuple(partitions.get(k) for k in PARTITION_KEYS)


class State:
    def __init__(self, latest: dict[tuple, str] | None = None):
        self._latest = latest or {}

    @classmethod
    def load(cls, league: str) -> "State":
        latest = {}
        with db.connect() as conn, conn.cursor() as cur:
            for endpoint in sorted(db.existing_tables(cur, league)):
                cur.execute(
                    f"""
                    SELECT
                        payload:_meta.season_id::int AS season_id,
                        payload:_meta.team_id::int   AS team_id,
                        payload:_meta.game_id::int   AS game_id,
                        content_hash
                    FROM `{db.raw_catalog()}`.`{league}`.`{endpoint}`
                    QUALIFY row_number() OVER (
                        PARTITION BY season_id, team_id, game_id
                        ORDER BY payload:_meta.fetched_at::timestamp DESC
                    ) = 1
                    """
                )
                for row in cur.fetchall():
                    latest[(endpoint, row.season_id, row.team_id, row.game_id)] = row.content_hash
        return cls(latest)

    def latest_hash(self, endpoint: str, partitions: dict) -> str | None:
        return self._latest.get(_key(endpoint, partitions))

    def has(self, endpoint: str, partitions: dict) -> bool:
        return _key(endpoint, partitions) in self._latest

    def record(self, endpoint: str, partitions: dict, content_hash: str) -> None:
        self._latest[_key(endpoint, partitions)] = content_hash
