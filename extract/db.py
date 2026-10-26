"""Connection to the Databricks SQL warehouse, from DATABRICKS_HOST / _HTTP_PATH / _TOKEN."""

import os

from databricks import sql


def connect():
    return sql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"]
        .removeprefix("https://")
        .rstrip("/"),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )


def raw_catalog() -> str:
    return os.environ.get("RAW_CATALOG", "raw")


def existing_tables(cur, league: str) -> set[str]:
    cur.execute(f"SHOW TABLES IN `{raw_catalog()}`.`{league}`")
    return {row.tableName for row in cur.fetchall()}
