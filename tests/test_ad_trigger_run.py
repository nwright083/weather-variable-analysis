"""
test_ad_trigger_run.py — end-to-end run_trigger behavior for the money-safety wiring:

  * threshold is bound to the selected model (default exact_pittsburgh -> 0.3681),
  * an explicit override still wins,
  * dry-run performs NO provider calls; a live+allowed run does,
  * the weekday-aware coverage window uses the PEAK ORI across covered days
    (a Friday run covers Sat + Sun + Mon).

Everything runs against temp forecast/meta files and an injected spy provider.

Run:  python -m pytest tests/test_ad_trigger_run.py -q
"""

import os
import sys
import json
import datetime

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import ad_config
import ad_trigger

# Exact Pittsburgh coefficients (no spatial terms) — matches odor_forecast_core.COEFFS_PITTSBURGH
EXACT_COEFFS = {
    "const": 3.559257, "temperature": 0.127472, "temperature_squared": -0.000564,
    "solar_radiation": -0.016272, "relative_humidity": -0.049634, "wind_speed": -0.173865,
    "precipitation": -0.908541, "diurnal_temperature_range": 0.241257,
    "boundary_layer_height": -0.000282, "atmospheric_pressure": -0.005154,
}
PRESSURE_OFFSET = 17.4


def _cell(dtr=15.0):
    return {
        "temp": 78.5, "temp_sq": 6162.25, "solar": 180.0, "rh": 72.0, "wind_speed": 6.5,
        "precip": 0.0, "dtr": dtr, "blh": 850.0, "pressure": 1000.5,
    }


class SpyProvider:
    def __init__(self):
        self.activated = []
        self.deactivated = []

    @property
    def name(self):
        return "spy"

    def activate_campaign(self, tract_id, tract_name, start_date, end_date, ori_score, metadata=None):
        self.activated.append(tract_id)
        return {"status": "ok", "campaign_id": f"spy-{tract_id}"}

    def deactivate_campaign(self, campaign_id):
        self.deactivated.append(campaign_id)
        return {"status": "ok", "campaign_id": campaign_id}

    def get_campaign_status(self, campaign_id):
        return {"status": "ok", "campaign_id": campaign_id, "state": "active"}

    def list_active_campaigns(self):
        return []


def _write(tmp_path, dates, cells_by_date, coeffs=None):
    """Write forecast.json + meta.json into tmp_path and point ad_config at them."""
    tract_ids = ["21157950101", "21157950102"]
    locations = [{"id": t, "zip": t, "name": f"Tract {t}", "lat": 37.0, "lon": -88.3} for t in tract_ids]
    features = {}
    for d in dates:
        features[d] = {t: dict(cells_by_date[d]) for t in tract_ids}
    forecast = {"dates": dates, "locations": locations, "features": features}
    meta = {"pressure_offset": PRESSURE_OFFSET,
            "coeffs": {"exact_pittsburgh": coeffs or EXACT_COEFFS}}

    fp = tmp_path / "forecast.json"
    mp = tmp_path / "meta.json"
    fp.write_text(json.dumps(forecast))
    mp.write_text(json.dumps(meta))

    ad_config.FORECAST_JSON = str(fp)
    ad_config.META_JSON = str(mp)
    ad_config.STATE_FILE = str(tmp_path / "ad_state.json")
    ad_config.LOG_FILE = str(tmp_path / "ad_decisions.log")


@pytest.fixture
def restore_config():
    saved = {k: getattr(ad_config, k) for k in
             ("FORECAST_JSON", "META_JSON", "STATE_FILE", "LOG_FILE", "MODEL_MODE", "ORI_THRESHOLD")}
    yield
    for k, v in saved.items():
        setattr(ad_config, k, v)


WED = datetime.date(2026, 7, 22)   # Wednesday -> covers Thu 2026-07-23
FRI = datetime.date(2026, 7, 24)   # Friday    -> covers Sat/Sun/Mon


class TestThresholdBinding:
    def test_default_model_threshold_is_0_3681(self, tmp_path, restore_config):
        ad_config.MODEL_MODE = "exact_pittsburgh"
        ad_config.ORI_THRESHOLD = None
        _write(tmp_path, ["2026-07-23"], {"2026-07-23": _cell()})
        result = ad_trigger.run_trigger(dry_run=True, provider_name="mock", today=WED)
        assert result["results"][0]["threshold"] == 0.3681

    def test_cli_override_wins(self, tmp_path, restore_config):
        ad_config.MODEL_MODE = "exact_pittsburgh"
        ad_config.ORI_THRESHOLD = None
        _write(tmp_path, ["2026-07-23"], {"2026-07-23": _cell()})
        result = ad_trigger.run_trigger(dry_run=True, provider_name="mock", threshold=0.5, today=WED)
        assert result["results"][0]["threshold"] == 0.5


class TestLiveGateEffect:
    def test_dry_run_makes_no_provider_calls(self, tmp_path, restore_config):
        ad_config.MODEL_MODE = "exact_pittsburgh"
        ad_config.ORI_THRESHOLD = None
        _write(tmp_path, ["2026-07-23"], {"2026-07-23": _cell()})
        spy = SpyProvider()
        # threshold 0.0 -> every tract triggers, so if anything were live it WOULD call
        result = ad_trigger.run_trigger(
            live=False, provider_name="mock", threshold=0.0, today=WED, provider=spy,
        )
        assert spy.activated == []               # nothing was actually deployed
        assert len(result["activated"]) == 2      # ...but the plan shows what WOULD deploy

    def test_live_mock_calls_provider(self, tmp_path, restore_config):
        ad_config.MODEL_MODE = "exact_pittsburgh"
        ad_config.ORI_THRESHOLD = None
        _write(tmp_path, ["2026-07-23"], {"2026-07-23": _cell()})
        spy = SpyProvider()
        ad_trigger.run_trigger(
            live=True, provider_name="mock", threshold=0.0, today=WED, provider=spy,
        )
        assert set(spy.activated) == {"21157950101", "21157950102"}


class TestCoverageWindowPeak:
    def test_friday_uses_peak_ori_across_weekend(self, tmp_path, restore_config):
        ad_config.MODEL_MODE = "exact_pittsburgh"
        ad_config.ORI_THRESHOLD = None
        # Sunday has the highest diurnal range -> highest ORI; peak must pick Sunday.
        dates = ["2026-07-25", "2026-07-26", "2026-07-27"]  # Sat, Sun, Mon
        cells = {
            "2026-07-25": _cell(dtr=5.0),
            "2026-07-26": _cell(dtr=25.0),
            "2026-07-27": _cell(dtr=10.0),
        }
        _write(tmp_path, dates, cells)
        result = ad_trigger.run_trigger(dry_run=True, provider_name="mock", today=FRI)
        r = result["results"][0]
        # peak day is Sunday, and its ORI should be the max of the three days
        assert r["date"] == "2026-07-26"
        sat = ad_trigger.compute_ori_from_features(cells["2026-07-25"], EXACT_COEFFS, PRESSURE_OFFSET)
        sun = ad_trigger.compute_ori_from_features(cells["2026-07-26"], EXACT_COEFFS, PRESSURE_OFFSET)
        assert r["ori"] == sun and sun > sat
