"""Open-Meteo requests must retry transient failures before falling back to mock data.

Background: the daily GitHub Actions run on 2026-09-08 failed with "Open-Meteo returned no live
data (mock fallback)" after 20 consecutive successes, while the same request succeeded locally
minutes later. A single transient HTTP error must not cost a day of forecasts.
"""
import sys, os
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odor_forecast_core as core


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


def _scripted_get(script):
    """Return a fake requests.get that pops one scripted outcome per call (exception or response)."""
    calls = []

    def fake_get(url, timeout=None, **kw):
        calls.append({"url": url, "timeout": timeout})
        outcome = script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake_get.calls = calls
    return fake_get


def test_retries_connection_errors_then_succeeds(monkeypatch):
    fake = _scripted_get([requests.ConnectionError("reset"), requests.Timeout("slow"), _Resp(200, {"daily": 1})])
    monkeypatch.setattr(core.requests, "get", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core.fetch_open_meteo_json("https://api.open-meteo.com/x") == {"daily": 1}
    assert len(fake.calls) == 3


def test_retries_on_429_and_5xx(monkeypatch):
    fake = _scripted_get([_Resp(429), _Resp(503), _Resp(200, {"hourly": 2})])
    monkeypatch.setattr(core.requests, "get", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core.fetch_open_meteo_json("u") == {"hourly": 2}
    assert len(fake.calls) == 3


def test_gives_up_after_max_attempts_and_reraises(monkeypatch):
    fake = _scripted_get([requests.ConnectionError("down")] * 4)
    monkeypatch.setattr(core.requests, "get", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    with pytest.raises(requests.ConnectionError):
        core.fetch_open_meteo_json("u", attempts=4)
    assert len(fake.calls) == 4


def test_does_not_retry_client_errors_other_than_429(monkeypatch):
    fake = _scripted_get([_Resp(400), _Resp(200)])
    monkeypatch.setattr(core.requests, "get", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        core.fetch_open_meteo_json("u")
    assert len(fake.calls) == 1


def test_backoff_sleeps_grow_between_attempts(monkeypatch):
    sleeps = []
    fake = _scripted_get([_Resp(503), _Resp(503), _Resp(200)])
    monkeypatch.setattr(core.requests, "get", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    core.fetch_open_meteo_json("u")
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]


def test_fetch_forecasts_uses_retrying_fetch_and_reports_failure(monkeypatch, capsys):
    """When every attempt fails, fetch_forecasts still returns mock data but the cause is printed."""
    monkeypatch.setattr(core, "fetch_open_meteo_json", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("boom")))
    df, is_mock = core.fetch_forecasts(core.LOCATIONS)
    assert is_mock is True and len(df) > 0
    assert "boom" in capsys.readouterr().err
