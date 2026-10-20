"""Copy local raw files to the Unity Catalog Volume: /Volumes/<catalog>/<league>/<volume>/...

Files already in the Volume are skipped. Raw files are immutable (each has a
unique fetched_at name), so existence is enough to know it's been uploaded.
"""

import os
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from extract.raw import RAW_ROOT


def volume_root(league: str) -> str:
    catalog = os.environ.get("RAW_CATALOG", "raw")
    volume = os.environ.get("RAW_VOLUME", "landing")
    return f"/Volumes/{catalog}/{league}/{volume}"


def upload(league: str) -> tuple[int, int]:
    """Upload new files for `league`. Returns (uploaded, skipped)."""
    # Reads DATABRICKS_HOST and DATABRICKS_TOKEN from the environment.
    w = WorkspaceClient()
    local_root = RAW_ROOT / league
    remote_root = volume_root(league)

    uploaded = skipped = 0
    for path in sorted(local_root.rglob("*.json")):
        remote = f"{remote_root}/{path.relative_to(local_root).as_posix()}"
        if _exists(w, remote):
            skipped += 1
            continue
        with path.open("rb") as f:
            w.files.upload(remote, f, overwrite=False)
        uploaded += 1
        print(f"uploaded {remote}")
    return uploaded, skipped


def _exists(w: WorkspaceClient, remote: str) -> bool:
    try:
        w.files.get_metadata(remote)
        return True
    except NotFound:
        return False
