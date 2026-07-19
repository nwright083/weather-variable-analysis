"""
test_eltoro_client.py — the El Toro REST client: OAuth2 client-credentials token
management (fetch, cache, refresh) and the order-line endpoints we use.

All tests run against an injected fake HTTP session and a controllable clock —
never the network.

Run:  python -m pytest tests/test_eltoro_client.py -q
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ad_providers.eltoro_client import ElToroClient, ElToroApiError


TOKEN_URL = "https://auth.example/token"
BASE_URL = "https://api.example"


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    """Records requests and returns responses from a handler(method, url, kwargs)."""

    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._handler("POST", url, kwargs)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._handler("GET", url, kwargs)


class Clock:
    """Controllable monotonic clock."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _default_handler(token="TOK-1", expires_in=300):
    """Handler: returns an access token for the token URL, {} otherwise."""
    def handler(method, url, kwargs):
        if url == TOKEN_URL:
            return FakeResponse(200, {"access_token": token, "token_type": "bearer",
                                      "expires_in": expires_in})
        return FakeResponse(200, {"ok": True})
    return handler


def _make_client(handler=None, clock=None, token_calls=None):
    handler = handler or _default_handler()
    clock = clock or Clock()
    return ElToroClient(
        client_id="CID",
        client_secret="SECRET",
        base_url=BASE_URL,
        token_url=TOKEN_URL,
        session=FakeSession(handler),
        clock=clock,
    )


class TestTokenManagement:
    def test_token_request_uses_client_credentials_form(self):
        client = _make_client()
        client.get_order_line("ol-1")  # triggers a token fetch
        token_call = [c for c in client._session.calls if c[1] == TOKEN_URL][0]
        method, url, kwargs = token_call
        assert method == "POST"
        data = kwargs["data"]
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "CID"
        assert data["client_secret"] == "SECRET"
        # form-urlencoded content type
        headers = kwargs.get("headers", {})
        assert headers.get("Content-Type") == "application/x-www-form-urlencoded"

    def test_token_is_cached_between_calls(self):
        client = _make_client()
        client.get_order_line("ol-1")
        client.get_order_line("ol-2")
        token_calls = [c for c in client._session.calls if c[1] == TOKEN_URL]
        assert len(token_calls) == 1  # fetched once, reused

    def test_token_refreshes_after_expiry(self):
        clock = Clock()
        client = _make_client(clock=clock)
        client.get_order_line("ol-1")
        clock.advance(400)  # past the 300s expiry (plus refresh margin)
        client.get_order_line("ol-2")
        token_calls = [c for c in client._session.calls if c[1] == TOKEN_URL]
        assert len(token_calls) == 2

    def test_bearer_token_sent_on_api_calls(self):
        client = _make_client()
        client.get_order_line("ol-1")
        api_call = [c for c in client._session.calls if c[1] != TOKEN_URL][0]
        headers = api_call[2].get("headers", {})
        assert headers.get("Authorization") == "Bearer TOK-1"

    def test_token_fetch_failure_raises(self):
        def handler(method, url, kwargs):
            if url == TOKEN_URL:
                return FakeResponse(401, {"error": "invalid_client"})
            return FakeResponse(200, {})
        client = _make_client(handler=handler)
        with pytest.raises(ElToroApiError):
            client.get_order_line("ol-1")


class TestOrderLineEndpoints:
    def test_get_order_line_hits_correct_url(self):
        client = _make_client()
        client.get_order_line("ol-abc")
        api_call = [c for c in client._session.calls if c[1] != TOKEN_URL][0]
        assert api_call[0] == "GET"
        assert api_call[1] == f"{BASE_URL}/v1/order-lines/ol-abc"

    def test_request_review_posts_action_url(self):
        client = _make_client()
        client.request_review("ol-abc")
        api_call = [c for c in client._session.calls if c[1] != TOKEN_URL][0]
        assert api_call[0] == "POST"
        assert api_call[1] == f"{BASE_URL}/v1/order-lines/ol-abc:requestReview"

    def test_cancel_deployment_posts_action_url(self):
        client = _make_client()
        client.cancel_deployment("ol-abc")
        api_call = [c for c in client._session.calls if c[1] != TOKEN_URL][0]
        assert api_call[0] == "POST"
        assert api_call[1] == f"{BASE_URL}/v1/order-lines/ol-abc:cancelDeployment"

    def test_list_order_lines_hits_collection_url(self):
        client = _make_client()
        client.list_order_lines()
        api_call = [c for c in client._session.calls if c[1] != TOKEN_URL][0]
        assert api_call[0] == "GET"
        assert api_call[1] == f"{BASE_URL}/v1/order-lines"

    def test_api_error_status_raises(self):
        def handler(method, url, kwargs):
            if url == TOKEN_URL:
                return FakeResponse(200, {"access_token": "T", "expires_in": 300})
            return FakeResponse(500, {"error": "boom"}, text="boom")
        client = _make_client(handler=handler)
        with pytest.raises(ElToroApiError):
            client.get_order_line("ol-1")

    def test_get_order_line_returns_parsed_json(self):
        def handler(method, url, kwargs):
            if url == TOKEN_URL:
                return FakeResponse(200, {"access_token": "T", "expires_in": 300})
            return FakeResponse(200, {"id": "ol-abc", "status": "ACTIVE"})
        client = _make_client(handler=handler)
        result = client.get_order_line("ol-abc")
        assert result["id"] == "ol-abc"
        assert result["status"] == "ACTIVE"
