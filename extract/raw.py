"""Write API responses to the local raw store, one file per call.

Layout (mirrors the Volume, so upload is a straight copy):
    data/raw/<league>/<endpoint>/[season_id=<n>/]<fetched_at>.json

Each file is a single-line JSON envelope:
    {"_meta": {league, endpoint, season_id, params, fetched_at}, "response": <API JSON>}
The response is stored as returned; nothing is renamed or dropped.

A response identical to the newest file in the same folder is not saved again,
so the files in a folder are a history of changes, not of fetches.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"

# Never write credentials into raw files.
_REDACTED_PARAMS = {"key", "client_code", "fmt", "lang"}


def save(league: str, endpoint: str, response, params: dict, season_id: int | None = None) -> Path | None:
    """Write the response to a new file, or return None if it matches the newest saved one."""
    folder = RAW_ROOT / league / endpoint
    if season_id is not None:
        folder = folder / f"season_id={season_id}"
    if _normalize(response) == _normalize(_latest_response(folder)):
        return None

    fetched_at = datetime.now(timezone.utc)
    envelope = {
        "_meta": {
            "league": league,
            "endpoint": endpoint,
            "season_id": season_id,
            "params": {k: v for k, v in params.items() if k not in _REDACTED_PARAMS},
            "fetched_at": fetched_at.isoformat(),
        },
        "response": response,
    }

    folder.mkdir(parents=True, exist_ok=True)

    # No colons: the filename has to be valid on Windows too.
    path = folder / f"{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def _normalize(value):
    """For comparison only: HockeyTech returns an empty field as [] on some calls and {} on
    others (seen on `broadcasters`), which would look like a change on every other fetch."""
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()} or None
    if isinstance(value, list):
        return [_normalize(v) for v in value] or None
    return value


def _latest_response(folder: Path):
    # Filenames are UTC timestamps, so the lexically last one is the newest.
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))["response"]
