"""Load new raw files from the Volume into raw tables with COPY INTO.

One table per endpoint (raw.<league>.<endpoint>), one row per file:
    payload      VARIANT    the whole file (_meta envelope + untouched API response)
    source_file  STRING     path of the file in the Volume
    loaded_at    TIMESTAMP  when this load ran

COPY INTO remembers which files it has loaded, so rerunning it only picks up new
files. These tables are what dbt declares as sources; dbt reads them, never writes.
"""

import os

from databricks import sql

from extract.raw import RAW_ROOT
from extract.upload import volume_root


def load(league: str) -> dict[str, int]:
    """COPY INTO every endpoint the league has files for. Returns rows inserted per endpoint."""
    catalog = os.environ.get("RAW_CATALOG", "raw")
    endpoints = sorted(p.name for p in (RAW_ROOT / league).iterdir() if p.is_dir())
    inserted = {}

    with sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"].removeprefix("https://").rstrip("/"),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn, conn.cursor() as cur:
        for endpoint in endpoints:
            table = f"`{catalog}`.`{league}`.`{endpoint}`"
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    payload     VARIANT   COMMENT 'Whole raw file: _meta envelope + untouched API response',
                    source_file STRING    COMMENT 'File path in the Volume',
                    loaded_at   TIMESTAMP COMMENT 'When COPY INTO loaded this file'
                )
                COMMENT 'Raw {league} {endpoint} responses. Written only by extract/load.py.'
                """
            )
            # Read each file as one text blob and parse it ourselves, so the
            # VARIANT holds exactly the file's JSON with no schema inference.
            cur.execute(
                f"""
                COPY INTO {table}
                FROM (
                    SELECT
                        parse_json(value)   AS payload,
                        _metadata.file_path AS source_file,
                        current_timestamp() AS loaded_at
                    FROM '{volume_root(league)}/{endpoint}/'
                )
                FILEFORMAT = TEXT
                -- recursiveFileLookup: descend into season_id=<n>/ folders without
                -- turning them into partition columns (season_id is in _meta already).
                FORMAT_OPTIONS ('wholeText' = 'true', 'recursiveFileLookup' = 'true')
                """
            )
            result = cur.fetchone()
            inserted[endpoint] = int(result.num_inserted_rows) if result else 0
    return inserted
