"""Databricks settings and the SQL warehouse connection.

Every environment variable the extractor reads is read here (see .env.example), except
DATABRICKS_HOST / DATABRICKS_TOKEN for the Files API, which the Databricks SDK reads
itself in upload.py.
"""

import os

from databricks import sql
from databricks.sql.client import Connection, Cursor


def connect() -> Connection:
    return sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"]
        .removeprefix("https://")
        .rstrip("/"),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


def raw_catalog() -> str:
    return os.environ.get("RAW_CATALOG", "raw")


def raw_volume() -> str:
    return os.environ.get("RAW_VOLUME", "landing")


def raw_table(league: str, endpoint: str) -> str:
    """Quoted name of an endpoint's raw table: `raw`.`pwhl`.`schedule`."""
    return f"`{raw_catalog()}`.`{league}`.`{endpoint}`"


def volume_root(league: str) -> str:
    """Where a league's raw files live in Unity Catalog: /Volumes/raw/pwhl/landing."""
    return f"/Volumes/{raw_catalog()}/{league}/{raw_volume()}"


def existing_tables(cur: Cursor, league: str) -> set[str]:
    cur.execute(f"show tables in `{raw_catalog()}`.`{league}`")
    return {row.tableName for row in cur.fetchall()}
