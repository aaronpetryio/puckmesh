"""Load new raw files from the Volume into raw tables with COPY INTO.

One table per endpoint (raw.<league>.<endpoint>), one row per file:
    payload       VARIANT    the whole file (_meta envelope + untouched API response)
    source_file   STRING     path of the file in the Volume
    loaded_at     TIMESTAMP  when this load ran
    content_hash  STRING     _meta.content_hash: what the extractor compares against

COPY INTO remembers which files it has loaded, so rerunning it only picks up new
files. These tables are what dbt declares as sources; dbt reads them, never writes.
"""

import json

from extract import db
from extract.raw import RAW_ROOT, content_hash
from extract.upload import volume_root


def load(league: str) -> dict[str, int]:
    """COPY INTO every endpoint the league has files for. Returns rows inserted per endpoint."""
    endpoints = sorted(p.name for p in (RAW_ROOT / league).iterdir() if p.is_dir())
    inserted = {}

    with db.connect() as conn, conn.cursor() as cur:
        for endpoint in endpoints:
            table = f"`{db.raw_catalog()}`.`{league}`.`{endpoint}`"
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    payload      VARIANT   COMMENT 'Whole raw file: _meta envelope + untouched API response',
                    source_file  STRING    COMMENT 'File path in the Volume',
                    loaded_at    TIMESTAMP COMMENT 'When COPY INTO loaded this file',
                    content_hash STRING    COMMENT 'SHA-256 of the response content (extract/raw.py)'
                )
                COMMENT 'Raw {league} {endpoint} responses. Written only by extract/load.py.'
                """
            )
            _add_hash_column(cur, table)
            # Read each file as one text blob and parse it ourselves, so the
            # VARIANT holds exactly the file's JSON with no schema inference.
            cur.execute(
                f"""
                COPY INTO {table}
                FROM (
                    SELECT
                        parse_json(value)                                  AS payload,
                        _metadata.file_path                                AS source_file,
                        current_timestamp()                                AS loaded_at,
                        parse_json(value):_meta.content_hash::string       AS content_hash
                    FROM '{volume_root(league)}/{endpoint}/'
                )
                FILEFORMAT = TEXT
                -- recursiveFileLookup: descend into season_id=<n>/ folders without
                -- turning them into partition columns (they're in _meta already).
                FORMAT_OPTIONS ('wholeText' = 'true', 'recursiveFileLookup' = 'true')
                """
            )
            result = cur.fetchone()
            inserted[endpoint] = int(result.num_inserted_rows) if result else 0
    return inserted


def backfill_hashes(league: str) -> dict[str, int]:
    """One-time: set content_hash on rows loaded before files carried one.

    Hashes are computed from the local copies of those files (identical to the Volume's),
    matched on file path. The payload itself is never modified.
    """
    updated = {}
    with db.connect() as conn, conn.cursor() as cur:
        for endpoint in sorted(db.existing_tables(cur, league)):
            table = f"`{db.raw_catalog()}`.`{league}`.`{endpoint}`"
            _add_hash_column(cur, table)
            cur.execute(f"SELECT source_file FROM {table} WHERE content_hash IS NULL")
            missing = [row.source_file for row in cur.fetchall()]
            values = []
            for source_file in missing:
                relative = source_file.split(f"/{league}/landing/", 1)[1]
                local = RAW_ROOT / league / relative
                response = json.loads(local.read_text(encoding="utf-8"))["response"]
                values.append((source_file, content_hash(response)))
            for start in range(0, len(values), 200):
                batch = values[start : start + 200]
                rows = ", ".join(f"('{f}', '{h}')" for f, h in batch)
                cur.execute(
                    f"""
                    MERGE INTO {table} AS t
                    USING (SELECT * FROM VALUES {rows} AS v(source_file, content_hash)) AS v
                    ON t.source_file = v.source_file
                    WHEN MATCHED AND t.content_hash IS NULL THEN UPDATE SET t.content_hash = v.content_hash
                    """
                )
            updated[endpoint] = len(values)
    return updated


def _add_hash_column(cur, table: str) -> None:
    # Tables created before content hashes existed don't have the column yet.
    cur.execute(f"DESCRIBE TABLE {table}")
    if "content_hash" not in {row.col_name for row in cur.fetchall()}:
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN content_hash STRING COMMENT 'SHA-256 of the response content (extract/raw.py)'"
        )
