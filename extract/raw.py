"""Write API responses to the local raw store, one file per call.

Layout (mirrors the Volume, so upload is a straight copy):
    data/raw/<league>/<endpoint>/[season_id=<n>/[team_id=<n>/|game_id=<n>/]]<fetched_at>.json

Each file is a single-line JSON envelope:
    {"_meta": {league, endpoint, <partition keys>, params, fetched_at, content_hash},
     "response": <API JSON>}
Partition keys (season_id, team_id, game_id) are whatever the call was scoped to.
The response is stored as returned; nothing is renamed or dropped.

A response whose content hash matches the latest stored one for the same endpoint and
partition is not saved again, so stored files are a history of changes, not of fetches.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from extract.client import Json
from extract.state import State

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"

# Request parameters left out of _meta: the league's key and client code (public, but no
# reason to copy them into every file), and the format settings every call shares.
_OMITTED_PARAMS = {"key", "client_code", "fmt", "lang"}


def content_hash(response: Json) -> str:
    """SHA-256 of the response's content.

    Key order and the []/{} empty-field quirk are ignored (see `_normalize`).
    """
    canonical = json.dumps(
        _normalize(response), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save(
    league: str,
    endpoint: str,
    response: Json,
    params: dict,
    state: State,
    **partitions: int,
) -> Path | None:
    """Write the response to a new file; return None if its content is already stored.

    `partitions` (e.g. season_id=8, team_id=4) become nested folders, in the order
    given, and are recorded in _meta.
    """
    digest = content_hash(response)
    if state.latest_hash(endpoint, partitions) == digest:
        return None

    fetched_at = datetime.now(UTC)
    envelope = {
        "_meta": {
            "league": league,
            "endpoint": endpoint,
            **partitions,
            "params": {k: v for k, v in params.items() if k not in _OMITTED_PARAMS},
            "fetched_at": fetched_at.isoformat(),
            "content_hash": digest,
        },
        "response": response,
    }

    folder = RAW_ROOT / league / endpoint
    for key, value in partitions.items():
        folder = folder / f"{key}={value}"
    folder.mkdir(parents=True, exist_ok=True)

    # No colons: the filename has to be valid on Windows too.
    path = folder / f"{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    state.record(endpoint, partitions, digest)
    return path


def _normalize(value: Any) -> Any:
    """Treat empty lists and empty dicts alike.

    HockeyTech returns an empty field as [] on some calls and {} on others (seen on
    `broadcasters`), which would look like a change on every other fetch.
    """
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()} or None
    if isinstance(value, list):
        return [_normalize(v) for v in value] or None
    return value
