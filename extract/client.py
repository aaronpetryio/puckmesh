"""HockeyTech / LeagueStat API client.

HockeyTech powers stats for several leagues; each one is identified by a
client_code and a public key embedded in that league's own website.
"""

import json
import time
from typing import Any

import requests

# A parsed API response.
Json = dict[str, Any]

BASE_URL = "https://lscluster.hockeytech.com/feed/index.php"

# Not secrets: each key is public, embedded in the league's own website.
LEAGUES = {
    "pwhl": {"client_code": "pwhl", "key": "446521baf8c38984"},
}


class HockeyTechError(RuntimeError):
    """The API answered, but with an error payload (it often returns 200 for errors)."""


def parse_body(text: str) -> Json:
    """Parse a response body into JSON.

    `statviewfeed` endpoints wrap their JSON in parentheses (JSONP without a
    callback name); `modulekit` and `gc` return plain JSON when fmt=json.
    """
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    data = json.loads(text)
    if isinstance(data, dict) and "error" in data:
        raise HockeyTechError(data["error"])
    return data


def _is_transient(error: requests.RequestException) -> bool:
    """Worth retrying: connection trouble, timeouts, rate limiting, server errors."""
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return isinstance(error, (requests.ConnectionError, requests.Timeout))


class HockeyTechClient:
    """Throttled, retrying client for one league's feed."""

    def __init__(self, league: str, min_interval: float = 1.0, retries: int = 3):
        if league not in LEAGUES:
            raise ValueError(f"Unknown league {league!r}; known: {sorted(LEAGUES)}")
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.league = league
        self.min_interval = min_interval
        self.retries = retries
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "puckmesh (women's hockey analytics)"
        self._last_request = 0.0

    def get(self, **params: str | int) -> Json:
        """Call the feed with the league's credentials plus `params`.

        Retries transient failures with exponential backoff; a 4xx fails at once.
        """
        query = {**LEAGUES[self.league], "fmt": "json", "lang": "en", **params}
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                resp = self._session.get(BASE_URL, params=query, timeout=30)
                resp.raise_for_status()
                return parse_body(resp.text)
            except requests.RequestException as error:
                if attempt == self.retries or not _is_transient(error):
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _throttle(self) -> None:
        # Be polite: this is a public endpoint we don't own.
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
