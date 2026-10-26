"""What is already stored: the latest content hash per endpoint and partition.

Read from the raw tables, so it's the same answer on a laptop or a fresh CI runner.
Responses saved during this run are recorded too, so a run never saves the same
content twice even before it's been uploaded and loaded.
"""

from extract import db

# Partition keys a raw file can carry in _meta, in folder order.
PARTITION_KEYS = ("season_id", "team_id", "game_id")

Key = tuple[str, int | None, int | None, int | None]


def _key(endpoint: str, partitions: dict[str, int]) -> Key:
    return (endpoint, *(partitions.get(k) for k in PARTITION_KEYS))


class State:
    """Latest stored content hash for each endpoint and partition."""

    def __init__(self, latest: dict[Key, str] | None = None):
        self._latest = latest or {}

    @classmethod
    def load(cls, league: str) -> "State":
        latest = {}
        with db.connect() as conn, conn.cursor() as cur:
            for endpoint in sorted(db.existing_tables(cur, league)):
                # Table names can't be bound as parameters; this one comes from config.
                cur.execute(
                    f"""
                    select
                        payload:_meta.season_id::int as season_id,
                        payload:_meta.team_id::int as team_id,
                        payload:_meta.game_id::int as game_id,
                        content_hash
                    from {db.raw_table(league, endpoint)}
                    qualify row_number() over (
                        partition by season_id, team_id, game_id
                        order by payload:_meta.fetched_at::timestamp desc
                    ) = 1
                    """  # noqa: S608
                )
                for row in cur.fetchall():
                    key = (endpoint, row.season_id, row.team_id, row.game_id)
                    latest[key] = row.content_hash
        return cls(latest)

    def latest_hash(self, endpoint: str, partitions: dict[str, int]) -> str | None:
        return self._latest.get(_key(endpoint, partitions))

    def has(self, endpoint: str, partitions: dict[str, int]) -> bool:
        return _key(endpoint, partitions) in self._latest

    def record(
        self, endpoint: str, partitions: dict[str, int], content_hash: str
    ) -> None:
        self._latest[_key(endpoint, partitions)] = content_hash
