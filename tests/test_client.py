import pytest
import requests

from extract import client
from extract.client import HockeyTechClient, HockeyTechError, parse_body


def test_parse_body_plain_json():
    assert parse_body('{"a": 1}') == {"a": 1}


def test_parse_body_strips_jsonp_parentheses():
    assert parse_body(' ({"a": 1})\n') == {"a": 1}


def test_parse_body_raises_on_error_payload():
    with pytest.raises(HockeyTechError, match="bad key"):
        parse_body('{"error": "bad key"}')


class FakeResponse:
    def __init__(self, status: int, text: str = "{}"):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = 0

    def get(self, url, params, timeout):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)


def make_client(responses) -> tuple[HockeyTechClient, FakeSession]:
    c = HockeyTechClient("pwhl", min_interval=0)
    session = FakeSession(responses)
    c._session = session
    return c, session


@pytest.mark.usefixtures("no_sleep")
@pytest.mark.parametrize(
    "first", [FakeResponse(503), FakeResponse(429), requests.ConnectionError()]
)
def test_get_retries_transient_failures(first):
    c, session = make_client([first, FakeResponse(200, '{"ok": true}')])
    assert c.get(view="seasons") == {"ok": True}
    assert session.calls == 2


@pytest.mark.usefixtures("no_sleep")
def test_get_does_not_retry_client_errors():
    c, session = make_client([FakeResponse(404), FakeResponse(200)])
    with pytest.raises(requests.HTTPError):
        c.get(view="seasons")
    assert session.calls == 1


@pytest.mark.usefixtures("no_sleep")
def test_get_gives_up_after_retries():
    c, session = make_client([FakeResponse(500)] * 3)
    with pytest.raises(requests.HTTPError):
        c.get(view="seasons")
    assert session.calls == 3


def test_rejects_unknown_league_and_zero_retries():
    with pytest.raises(ValueError, match="Unknown league"):
        HockeyTechClient("nhl")
    with pytest.raises(ValueError, match="retries"):
        HockeyTechClient("pwhl", retries=0)
