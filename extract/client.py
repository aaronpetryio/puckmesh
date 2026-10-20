"""HockeyTech / LeagueStat API client.

HockeyTech powers stats for several leagues; each one is identified by a
client_code and a public key embedded in that league's own website.
"""

import json
import time

import requests

BASE_URL = "https://lscluster.hockeytech.com/feed/index.php"

LEAGUES = {
    "pwhl": {"client_code": "pwhl", "key": "446521baf8c38984"},
}


class HockeyTechError(RuntimeError):
    """The API answered, but with an error payload (it often returns 200 for errors)."""


def parse_body(text: str):
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


class HockeyTechClient:
    def __init__(self, league: str, min_interval: float = 1.0, retries: int = 3):
        if league not in LEAGUES:
            raise ValueError(f"Unknown league {league!r}; known: {sorted(LEAGUES)}")
        self.league = league
        self.min_interval = min_interval
        self.retries = retries
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "puckmesh (women's hockey analytics)"
        self._last_request = 0.0

    def get(self, **params):
        """Call the feed with the league's credentials plus `params`; return parsed JSON."""
        query = {**LEAGUES[self.league], "fmt": "json", "lang": "en", **params}
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                resp = self._session.get(BASE_URL, params=query, timeout=30)
                resp.raise_for_status()
                return parse_body(resp.text)
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if attempt == self.retries:
                    raise
                time.sleep(2**attempt)

    def _throttle(self):
        # Be polite: this is a public endpoint we don't own.
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
