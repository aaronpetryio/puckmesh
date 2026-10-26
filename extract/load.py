"""Load new raw files from the Volume into raw tables with COPY INTO.

One table per endpoint (raw.<league>.<endpoint>), one row per file:
    payload       VARIANT    the whole file (_meta envelope + untouched API response)
    source_file   STRING     path of the file in the Volume
    loaded_at     TIMESTAMP  when this load ran
    content_hash  STRING     _meta.content_hash: what the extractor compares against

COPY INTO remembers which files it has loaded, so rerunning it only picks up new
files. These tables are what dbt declares as sources; dbt reads them, never writes.

Table names can't be bound as query parameters, so they're formatted into the SQL
(`# noqa: S608` below); they come from config and endpoint names, never from data.
"""

import json

from databricks.sql.client import Cursor

from extract import db
from extract.raw import RAW_ROOT, content_hash

_PAYLOAD_COMMENT = "Whole raw file: _meta envelope + untouched API response"
_HASH_COMMENT = "SHA-256 of the response content (extract/raw.py)"
_MERGE_BATCH = 200


def load(league: str) -> dict[str, int]:
    """COPY INTO every endpoint the league has files for.

    Returns:
        Rows inserted per endpoint.
    """
    endpoints = sorted(p.name for p in (RAW_ROOT / league).iterdir() if p.is_dir())
    inserted = {}

    with db.connect() as conn, conn.cursor() as cur:
        for endpoint in endpoints:
            table = db.raw_table(league, endpoint)
            table_comment = (
                f"Raw {league} {endpoint} responses. Written only by extract/load.py."
            )
            cur.execute(
                f"""
                create table if not exists {table} (
                    payload variant comment '{_PAYLOAD_COMMENT}',
                    source_file string comment 'File path in the Volume',
                    loaded_at timestamp comment 'When COPY INTO loaded this file',
                    content_hash string comment '{_HASH_COMMENT}'
                )
                comment '{table_comment}'
                """
            )
            _add_hash_column(cur, table)
            # Read each file as one text blob and parse it ourselves, so the
            # VARIANT holds exactly the file's JSON with no schema inference.
            cur.execute(
                f"""
                copy into {table}
                from (
                    select
                        parse_json(value) as payload,
                        _metadata.file_path as source_file,
                        current_timestamp() as loaded_at,
                        parse_json(value):_meta.content_hash::string as content_hash
                    from '{db.volume_root(league)}/{endpoint}/'
                )
                fileformat = text
                -- recursiveFileLookup: descend into season_id=<n>/ folders without
                -- turning them into partition columns (they're in _meta already).
                format_options ('wholeText' = 'true', 'recursiveFileLookup' = 'true')
                """  # noqa: S608
            )
            result = cur.fetchone()
            inserted[endpoint] = int(result.num_inserted_rows) if result else 0
    return inserted


def backfill_hashes(league: str) -> dict[str, int]:
    """One-time: set content_hash on rows loaded before files carried one.

    Hashes are computed from the local copies of those files (identical to the
    Volume's), matched on file path. The payload itself is never modified.
    """
    updated = {}
    with db.connect() as conn, conn.cursor() as cur:
        for endpoint in sorted(db.existing_tables(cur, league)):
            table = db.raw_table(league, endpoint)
            _add_hash_column(cur, table)
            cur.execute(
                f"select source_file from {table} where content_hash is null"  # noqa: S608
            )
            missing = [row.source_file for row in cur.fetchall()]
            values = []
            for source_file in missing:
                relative = source_file.split(f"/{league}/landing/", 1)[1]
                local = RAW_ROOT / league / relative
                response = json.loads(local.read_text(encoding="utf-8"))["response"]
                values.append((source_file, content_hash(response)))
            for start in range(0, len(values), _MERGE_BATCH):
                batch = values[start : start + _MERGE_BATCH]
                # Bind the values as parameters: (:file_0, :hash_0), (:file_1, ...), ...
                rows = ", ".join(f"(:file_{i}, :hash_{i})" for i in range(len(batch)))
                params = {}
                for i, (source_file, digest) in enumerate(batch):
                    params[f"file_{i}"] = source_file
                    params[f"hash_{i}"] = digest
                cur.execute(
                    f"""
                    merge into {table} as target
                    using (
                        select * from values {rows} as v(source_file, content_hash)
                    ) as v
                    on target.source_file = v.source_file
                    when matched and target.content_hash is null
                        then update set target.content_hash = v.content_hash
                    """,  # noqa: S608
                    params,
                )
            updated[endpoint] = len(values)
    return updated


def _add_hash_column(cur: Cursor, table: str) -> None:
    # Tables created before content hashes existed don't have the column yet.
    cur.execute(f"describe table {table}")
    if "content_hash" not in {row.col_name for row in cur.fetchall()}:
        cur.execute(
            f"alter table {table} add column content_hash string "
            f"comment '{_HASH_COMMENT}'"
        )
