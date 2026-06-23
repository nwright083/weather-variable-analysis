# Static Odor Risk Forecast Website — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static, daily-regenerated GitHub Pages website that shows the Calvert City odor-risk 16-day forecast, 30-day historical calendar, and interactive map, with the ORI model computed live in the browser.

**Architecture:** A Python data generator (`generate_site.py`) calls shared logic in a new Streamlit-free `odor_forecast_core.py` to fetch weather and write raw model-feature JSON into `docs/data/`. A static HTML/JS shell (`docs/index.html` + `app.js` + `model.js`) loads that JSON and computes ORI client-side from coefficients exported in `meta.json`, giving live controls for prediction mode (incl. Custom), wind filter, penalty, and boost. GitHub Actions runs the generator on a daily cron and deploys `docs/` to Pages.

**Tech Stack:** Python 3.11 (requests, pandas, numpy), vanilla JavaScript, Leaflet.js (CDN), GitHub Actions, GitHub Pages.

## Global Constraints

- Python: standard-lib + `requests`, `pandas`, `numpy` only. No new heavy deps.
- `odor_forecast_core.py` MUST NOT import `streamlit` and MUST have no import-time side effects (no network calls, no `init_db()` at module load).
- The browser model math in `docs/model.js` MUST produce ORI values matching `odor_forecast_core.predict_ori` to within 0.1 for identical inputs.
- The single source of truth for coefficients and `PRESSURE_ELEVATION_OFFSET` is `odor_forecast_core.py`; `meta.json` is generated from it; `model.js` reads them from `meta.json` and never hardcodes them.
- Risk tiers (mirrored in Python `get_risk_meta` and JS `getRiskTier`): `<15` Clear `[22,163,74]`, `<30` Moderate `[202,138,4]`, `<50` Elevated `[234,88,12]`, else High `[220,38,38]`.
- `docs/` is the GitHub Pages publish root. Generated data lives in `docs/data/` and is git-ignored (produced fresh by the generator / CI).
- All work happens on the existing `static-forecast-site` branch.
- Run Python via the project venv: `.venv/bin/python`.

---

## File Structure

| File | Responsibility |
|---|---|
| `odor_forecast_core.py` (NEW) | Pure model + weather logic: constants, coefficients, `calculate_bearing`, `check_wind_alignment`, `get_risk_meta`, `predict_ori`, `fetch_forecasts`, `fetch_historical_weather`. No Streamlit. |
| `calvert_odor_forecaster.py` (MODIFY) | Streamlit UI only; imports all logic from core; wraps fetches with `st.cache_data`; passes wind args explicitly. |
| `generate_site.py` (NEW) | Headless cron entry point: fetch → build `forecast.json`, `historical.json`, `meta.json`; copy geojson into `docs/`. |
| `docs/index.html` (NEW) | Page shell: header, controls panel, four tab containers, CDN script tags. |
| `docs/style.css` (NEW) | Card/badge/calendar styling (ported from the Streamlit CSS look). |
| `docs/model.js` (NEW) | Pure ORI math (`computeZ`, `computeOri`, `getRiskTier`); dual-mode for browser + Node. |
| `docs/app.js` (NEW) | Data loading, controls, live recompute, tabs, Leaflet map, report tab. |
| `docs/.gitkeep`, `.gitignore` (MODIFY) | Ignore `docs/data/`. |
| `.github/workflows/forecast.yml` (NEW) | Daily cron + Pages deploy. |
| `DEPLOYMENT.md` (NEW) | One-time Pages setup + university-server crontab notes. |
| `scratch/test_forecast_engine.py` (MODIFY) | Retarget imports to `odor_forecast_core`. |
| `scratch/test_generate_site.py` (NEW) | Generator schema smoke test. |
| `scratch/test_js_model.py` (NEW) | JS↔Python ORI parity via Node. |

---

## Task 1: Extract `odor_forecast_core.py` and refactor the Streamlit app to use it

**Files:**
- Create: `odor_forecast_core.py`
- Modify: `calvert_odor_forecaster.py` (remove the moved logic; import from core)
- Test: `scratch/test_forecast_engine.py` (retarget imports)

**Interfaces:**
- Produces:
  - `IND_LAT: float`, `IND_LON: float`, `PRESSURE_ELEVATION_OFFSET: float = 17.4`
  - `LOCATIONS: dict[str, dict]` (keys like `"ZIP 42029 (Calvert City)"`, value `{"coords": (lat, lon)}`)
  - `COEFFS_PITTSBURGH: dict[str, float]`, `COEFFS_EST_CALVERT: dict[str, float]`
  - `calculate_bearing(lat2, lon2) -> float`
  - `check_wind_alignment(wind_from, location_or_bearing, tolerance=10.0) -> bool`
  - `get_risk_meta(ori) -> tuple[str, str, list[int]]`
  - `predict_ori(row, coeffs, *, use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0) -> float`
  - `fetch_forecasts(locations) -> tuple[pandas.DataFrame, bool]` (df, is_mock); no Streamlit calls
  - `fetch_historical_weather(locations) -> tuple[pandas.DataFrame, bool]`

- [ ] **Step 1: Create `odor_forecast_core.py` with constants, coefficients, and geometry helpers**

Create the file with this header and the geometry/risk logic (move `calculate_bearing`, `check_wind_alignment`, and `get_risk_meta` verbatim from `calvert_odor_forecaster.py`, plus the constants/coefficients):

```python
"""Pure odor-risk forecasting logic — no Streamlit, no import-time side effects.

Shared by the Streamlit app (calvert_odor_forecaster.py) and the static-site
generator (generate_site.py). This module is the single source of truth for the
model coefficients and the PRESSURE_ELEVATION_OFFSET.
"""
import math
import hashlib
import datetime
import numpy as np
import pandas as pd
import requests

# Center coordinates of the Calvert City Industrial Complex
IND_LAT = 37.0486
IND_LON = -88.3480

# Elevation-adjusted pressure offset (cross-city transfer correction):
# Pittsburgh training mean surface pressure = 980.93 hPa (~370 m ASL);
# Calvert City / western KY mean ≈ 998.3 hPa (~115 m ASL). Subtracting this offset
# expresses Calvert pressure in Pittsburgh's training frame, preserving synoptic
# anomaly signal while removing the elevation artifact.
PRESSURE_ELEVATION_OFFSET = 17.4  # hPa

LOCATIONS = {
    "ZIP 42029 (Calvert City)": {"coords": (37.0317, -88.3542)},
    "ZIP 42025 (Benton)": {"coords": (36.8576, -88.3506)},
    "ZIP 42045 (Grand Rivers)": {"coords": (37.0034, -88.2323)},
    "ZIP 42081 (Smithland)": {"coords": (37.1378, -88.3975)},
    "ZIP 42058 (Ledbetter)": {"coords": (37.0506, -88.4984)},
    "ZIP 42001 (Paducah)": {"coords": (37.0834, -88.6000)},
    "ZIP 42003 (Reidland)": {"coords": (37.0095, -88.5273)},
}

COEFFS_PITTSBURGH = {
    'const': 17.415789,
    'temperature': 0.114354,
    'temperature_squared': -0.000476,
    'solar_radiation': -0.013972,
    'relative_humidity': -0.057838,
    'wind_speed': -0.108479,
    'precipitation': -0.864070,
    'diurnal_temperature_range': 0.229181,
    'boundary_layer_height': -0.000410,
    'atmospheric_pressure': -0.017966,
}

COEFFS_EST_CALVERT = {
    'const': 18.000000,
    'temperature': 0.114354,
    'temperature_squared': -0.000476,
    'solar_radiation': -0.013972,
    'relative_humidity': -0.057838,
    'wind_speed': -0.150000,
    'precipitation': -0.864070,
    'diurnal_temperature_range': 0.229181,
    'boundary_layer_height': -0.000600,
    'atmospheric_pressure': -0.017966,
}


def calculate_bearing(lat2, lon2):
    lat1, lon1 = IND_LAT, IND_LON
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    bearing = math.degrees(math.atan2(dx, dy))
    return (bearing + 360) % 360


def check_wind_alignment(wind_from, location_or_bearing, tolerance=10.0):
    # (move the FULL body verbatim from calvert_odor_forecaster.py:172-212,
    #  including the centroid-math fallback and the 7 hardcoded ZIP sectors)
    ...


def get_risk_meta(ori):
    if ori < 15.0:
        return "Clear / Low Risk", "badge-clear", [22, 163, 74]
    elif ori < 30.0:
        return "Moderate Risk", "badge-moderate", [202, 138, 4]
    elif ori < 50.0:
        return "Elevated Risk", "badge-elevated", [234, 88, 12]
    else:
        return "High Risk", "badge-high", [220, 38, 38]
```

When copying `check_wind_alignment`, paste the exact body currently at `calvert_odor_forecaster.py:172-212` (do not retype the sector numbers from memory — copy them).

- [ ] **Step 2: Add `predict_ori` with explicit wind kwargs to core**

Append to `odor_forecast_core.py`:

```python
def predict_ori(row, coeffs, *, use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0):
    z = (
        coeffs['const'] +
        coeffs['temperature'] * row['temperature'] +
        coeffs['temperature_squared'] * row['temperature_squared'] +
        coeffs['solar_radiation'] * row['solar_radiation'] +
        coeffs['relative_humidity'] * row['relative_humidity'] +
        coeffs['wind_speed'] * row['wind_speed'] +
        coeffs['precipitation'] * row['precipitation'] +
        coeffs['diurnal_temperature_range'] * row['diurnal_temperature_range'] +
        coeffs['boundary_layer_height'] * row['boundary_layer_height'] +
        # Subtract elevation offset so Calvert pressure is in Pittsburgh's training frame.
        coeffs['atmospheric_pressure'] * (row['atmospheric_pressure'] - PRESSURE_ELEVATION_OFFSET)
    )
    if use_wind_filter:
        loc_val = row.get('location', row.get('bearing_from_source', 196.3))
        is_aligned = check_wind_alignment(row['wind_direction'], loc_val)
        if not is_aligned:
            z += math.log(max(wind_penalty, 1e-9))
        else:
            z += math.log(max(wind_boost, 1e-9))
    z = max(-60.0, min(60.0, z))
    return round(100.0 / (1.0 + math.exp(-z)), 1)
```

- [ ] **Step 3: Move both fetch functions into core (strip Streamlit)**

Move `fetch_forecasts` and `fetch_historical_weather` from `calvert_odor_forecaster.py` into `odor_forecast_core.py` verbatim, with exactly two changes each:
1. Delete the `@st.cache_data(...)` decorator line above each function.
2. In `fetch_forecasts`, delete the line `st.sidebar.error(f"Weather forecast API offline: {e}")` (the `except Exception as e:` block keeps the rest — it already returns `(df, True)`).

No other lines change. The functions already use `np`, `pd`, `requests`, `datetime`, `hashlib`, `math`, `calculate_bearing` — all available in core.

- [ ] **Step 4: Rewrite `calvert_odor_forecaster.py` to import from core**

Replace the moved definitions (constants, coefficients, `calculate_bearing`, `check_wind_alignment`, `get_risk_meta`, `predict_ori`, and the two fetch functions) with an import block near the top, just after the existing imports:

```python
import odor_forecast_core as core
from odor_forecast_core import (
    IND_LAT, IND_LON, PRESSURE_ELEVATION_OFFSET, LOCATIONS,
    COEFFS_PITTSBURGH, COEFFS_EST_CALVERT,
    calculate_bearing, check_wind_alignment, get_risk_meta,
)

# Streamlit-cached wrappers around the pure core fetchers
fetch_forecasts = st.cache_data(ttl=1800)(core.fetch_forecasts)
fetch_historical_weather = st.cache_data(ttl=3600)(core.fetch_historical_weather)
```

Then update the two `.apply(...)` call sites that compute ORI (currently `forecast_df.apply(lambda r: predict_ori(r, active_coeffs), axis=1)` and the historical one) to pass the wind controls explicitly:

```python
forecast_df['ori'] = forecast_df.apply(
    lambda r: core.predict_ori(
        r, active_coeffs,
        use_wind_filter=use_wind_filter, wind_penalty=wind_penalty, wind_boost=wind_boost,
    ), axis=1)
```

Apply the identical change to the historical `hist_df.apply(...)` call. Keep `init_db()` and all UI code in `calvert_odor_forecaster.py` unchanged. Also re-add the `surface_pressure`/`is_mock` sidebar warning if desired: after `forecast_df, is_mock = fetch_forecasts(LOCATIONS)`, optionally `if is_mock: st.sidebar.error("Weather forecast API offline — showing simulated data.")`.

- [ ] **Step 5: Retarget the existing tests to core**

In `scratch/test_forecast_engine.py`, change the import line:

```python
from odor_forecast_core import (
    predict_ori,
    COEFFS_PITTSBURGH, COEFFS_EST_CALVERT, PRESSURE_ELEVATION_OFFSET
)
```

The existing test bodies call `predict_ori(mock_row, COEFFS_*)` with no wind kwargs — they rely on the defaults (`use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0`), which match the old module-global defaults, so the asserted values are unchanged.

- [ ] **Step 6: Run the tests — expect all green**

Run: `.venv/bin/python -m pytest scratch/test_forecast_engine.py -v`
Expected: `5 passed`.

- [ ] **Step 7: Verify the Streamlit app still imports cleanly**

Run: `.venv/bin/python -c "import ast; ast.parse(open('calvert_odor_forecaster.py').read()); ast.parse(open('odor_forecast_core.py').read()); print('parse OK')"`
Then: `.venv/bin/python -c "import odor_forecast_core as c; print(round(c.predict_ori({'temperature':78,'temperature_squared':6084,'solar_radiation':180,'relative_humidity':72,'wind_speed':2.5,'precipitation':0.0,'diurnal_temperature_range':18,'boundary_layer_height':600,'atmospheric_pressure':1005,'wind_direction':10,'bearing_from_source':190}, c.COEFFS_PITTSBURGH),1))"`
Expected: prints a float (e.g. `93.2`), no Streamlit import error.

- [ ] **Step 8: Commit**

```bash
git add odor_forecast_core.py calvert_odor_forecaster.py scratch/test_forecast_engine.py
git commit -m "refactor: extract pure forecasting logic into odor_forecast_core"
```

---

## Task 2: `generate_site.py` — write the JSON data files

**Files:**
- Create: `generate_site.py`
- Test: `scratch/test_generate_site.py`

**Interfaces:**
- Consumes: `odor_forecast_core` (`fetch_forecasts`, `fetch_historical_weather`, `check_wind_alignment`, `calculate_bearing`, `COEFFS_PITTSBURGH`, `COEFFS_EST_CALVERT`, `PRESSURE_ELEVATION_OFFSET`, `LOCATIONS`).
- Produces:
  - `build_feature_payload(df, dates_sorted) -> dict` with keys `dates`, `locations`, `features`.
  - `build_meta() -> dict` with keys `generated_utc`, `source`, `pressure_offset`, `coeffs`, `mode_labels`, `custom_slider_ranges`, `wind_defaults`.
  - `main(output_dir="docs/data") -> None` writing `forecast.json`, `historical.json`, `meta.json`.
  - CLI: `python generate_site.py` writes into `docs/data/` and copies `calvert_zips.geojson` into `docs/`.

- [ ] **Step 1: Write the failing schema test**

Create `scratch/test_generate_site.py`:

```python
import os
import sys
import json
import tempfile
import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_site


def _fake_df(dates):
    rows = []
    for loc in generate_site.core.LOCATIONS:
        lat, lon = generate_site.core.LOCATIONS[loc]["coords"]
        for d in dates:
            rows.append({
                'date': d, 'location': loc, 'latitude': lat, 'longitude': lon,
                'temperature': 75.0, 'temp_min': 67.0, 'temp_max': 83.0,
                'temperature_squared': 75.0 ** 2, 'solar_radiation': 180.0,
                'relative_humidity': 70.0, 'wind_speed': 3.0, 'wind_direction': 200.0,
                'precipitation': 0.0, 'diurnal_temperature_range': 16.0,
                'boundary_layer_height': 800.0, 'atmospheric_pressure': 1005.0,
                'bearing_from_source': generate_site.core.calculate_bearing(lat, lon),
            })
    return pd.DataFrame(rows)


def test_build_feature_payload_schema():
    dates = ["2026-06-24", "2026-06-25"]
    df = _fake_df(dates)
    payload = generate_site.build_feature_payload(df, dates)
    assert payload["dates"] == dates
    assert {l["zip"] for l in payload["locations"]} == {"42029","42025","42045","42081","42058","42001","42003"}
    cell = payload["features"]["2026-06-24"]["42029"]
    for k in ["aligned","temp","temp_sq","solar","rh","wind_speed","wind_dir","precip","dtr","blh","pressure"]:
        assert k in cell, f"missing {k}"
    assert isinstance(cell["aligned"], bool)


def test_build_meta_has_coeffs_and_offset():
    meta = generate_site.build_meta()
    assert meta["pressure_offset"] == generate_site.core.PRESSURE_ELEVATION_OFFSET
    assert "estimated_calvert" in meta["coeffs"]
    assert "exact_pittsburgh" in meta["coeffs"]
    assert meta["coeffs"]["exact_pittsburgh"]["const"] == generate_site.core.COEFFS_PITTSBURGH["const"]
    assert set(meta["mode_labels"]) == {"estimated_calvert", "exact_pittsburgh"}
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `.venv/bin/python -m pytest scratch/test_generate_site.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'generate_site'`.

- [ ] **Step 3: Implement `generate_site.py`**

```python
"""Headless generator for the static odor-risk forecast site.

Fetches weather via odor_forecast_core, emits RAW model features (not ORI) plus
a meta file with coefficients, so the browser can compute ORI live for any mode.
"""
import os
import json
import shutil
import datetime

import odor_forecast_core as core

ZIP_FROM_LOCATION = {name: name.split(" ")[1] for name in core.LOCATIONS}  # "ZIP 42029 (..)" -> "42029"
ROOT = os.path.dirname(os.path.abspath(__file__))


def _location_directory():
    locs = []
    for name, info in core.LOCATIONS.items():
        lat, lon = info["coords"]
        locs.append({
            "zip": name.split(" ")[1],
            "name": name.split("(")[1].rstrip(")").strip() if "(" in name else name,
            "lat": lat, "lon": lon,
        })
    return locs


def build_feature_payload(df, dates_sorted):
    features = {}
    for d in dates_sorted:
        day = df[df["date"] == d]
        per_zip = {}
        for _, row in day.iterrows():
            zip_code = row["location"].split(" ")[1]
            aligned = core.check_wind_alignment(row["wind_direction"], row["location"])
            per_zip[zip_code] = {
                "aligned": bool(aligned),
                "temp": round(float(row["temperature"]), 2),
                "temp_sq": round(float(row["temperature_squared"]), 2),
                "solar": round(float(row["solar_radiation"]), 2),
                "rh": round(float(row["relative_humidity"]), 2),
                "wind_speed": round(float(row["wind_speed"]), 2),
                "wind_dir": round(float(row["wind_direction"]), 1),
                "precip": round(float(row["precipitation"]), 3),
                "dtr": round(float(row["diurnal_temperature_range"]), 2),
                "blh": round(float(row["boundary_layer_height"]), 1),
                "pressure": round(float(row["atmospheric_pressure"]), 2),
            }
        features[d] = per_zip
    return {"dates": list(dates_sorted), "locations": _location_directory(), "features": features}


def build_meta():
    custom_ranges = {
        "const": [-30.0, 30.0, 0.1],
        "temperature": [-0.5, 0.5, 0.001],
        "temperature_squared": [-0.005, 0.005, 0.00001],
        "solar_radiation": [-0.1, 0.1, 0.001],
        "relative_humidity": [-0.2, 0.2, 0.001],
        "wind_speed": [-0.5, 0.5, 0.001],
        "precipitation": [-2.0, 2.0, 0.01],
        "diurnal_temperature_range": [-0.5, 0.5, 0.001],
        "boundary_layer_height": [-0.005, 0.005, 0.00001],
        "atmospheric_pressure": [-0.1, 0.1, 0.001],
    }
    return {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Open-Meteo (NWP + ERA5)",
        "pressure_offset": core.PRESSURE_ELEVATION_OFFSET,
        "coeffs": {
            "estimated_calvert": core.COEFFS_EST_CALVERT,
            "exact_pittsburgh": core.COEFFS_PITTSBURGH,
        },
        "mode_labels": {
            "estimated_calvert": "Estimated Calvert City",
            "exact_pittsburgh": "Exact Pittsburgh Model",
        },
        "custom_slider_ranges": custom_ranges,
        "wind_defaults": {"filter": True, "penalty_pct": 75, "boost": 1.0},
    }


def main(output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "docs", "data")
    os.makedirs(output_dir, exist_ok=True)

    fdf, f_mock = core.fetch_forecasts(core.LOCATIONS)
    hdf, h_mock = core.fetch_historical_weather(core.LOCATIONS)
    if f_mock or h_mock:
        raise RuntimeError("Open-Meteo returned no live data (mock fallback); refusing to overwrite good data.")

    f_dates = sorted(fdf["date"].unique())
    h_dates = sorted(hdf["date"].unique())

    with open(os.path.join(output_dir, "forecast.json"), "w") as fh:
        json.dump(build_feature_payload(fdf, f_dates), fh)
    with open(os.path.join(output_dir, "historical.json"), "w") as fh:
        json.dump(build_feature_payload(hdf, h_dates), fh)
    with open(os.path.join(output_dir, "meta.json"), "w") as fh:
        json.dump(build_meta(), fh, indent=2)

    # Copy the ZIP boundary polygons next to index.html for Leaflet
    src_geo = os.path.join(ROOT, "calvert_zips.geojson")
    if os.path.exists(src_geo):
        shutil.copy(src_geo, os.path.join(ROOT, "docs", "calvert_zips.geojson"))

    print(f"Wrote forecast ({len(f_dates)}d), historical ({len(h_dates)}d), meta to {output_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the schema test — expect pass**

Run: `.venv/bin/python -m pytest scratch/test_generate_site.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run the generator live (network) and inspect output**

Run: `.venv/bin/python generate_site.py && .venv/bin/python -c "import json; d=json.load(open('docs/data/forecast.json')); print(len(d['dates']),'dates;', list(d['features'][d['dates'][0]]['42029'].keys()))"`
Expected: prints `16 dates;` and the cell key list including `aligned`, `temp`, `pressure`. (If Open-Meteo is unreachable, it raises by design — re-run later.)

- [ ] **Step 6: Commit**

```bash
git add generate_site.py scratch/test_generate_site.py
git commit -m "feat: add generate_site.py producing forecast/historical/meta JSON"
```

---

## Task 3: `docs/model.js` — client-side ORI math with Python parity test

**Files:**
- Create: `docs/model.js`
- Test: `scratch/test_js_model.py`

**Interfaces:**
- Produces (global `OdorModel` in browser; `module.exports` in Node):
  - `computeZ(cell, coeffs, pressureOffset) -> number`
  - `computeOri(cell, coeffs, opts) -> number` where `opts = {pressureOffset, windFilter, penalty, boost}`
  - `getRiskTier(ori) -> {label, cls, rgb:[r,g,b]}`
- `cell` keys: `temp, temp_sq, solar, rh, wind_speed, precip, dtr, blh, pressure, aligned`.

- [ ] **Step 1: Write `docs/model.js`**

```javascript
// Pure ORI math — mirrors odor_forecast_core.predict_ori exactly.
// Dual-mode: attaches to window.OdorModel in the browser and exports for Node tests.
(function (root) {
  function computeZ(cell, c, pressureOffset) {
    return c.const
      + c.temperature * cell.temp
      + c.temperature_squared * cell.temp_sq
      + c.solar_radiation * cell.solar
      + c.relative_humidity * cell.rh
      + c.wind_speed * cell.wind_speed
      + c.precipitation * cell.precip
      + c.diurnal_temperature_range * cell.dtr
      + c.boundary_layer_height * cell.blh
      + c.atmospheric_pressure * (cell.pressure - pressureOffset);
  }

  function computeOri(cell, c, opts) {
    var z = computeZ(cell, c, opts.pressureOffset);
    if (opts.windFilter) {
      z += cell.aligned
        ? Math.log(Math.max(opts.boost, 1e-9))
        : Math.log(Math.max(opts.penalty, 1e-9));
    }
    z = Math.max(-60, Math.min(60, z));
    return Math.round((100 / (1 + Math.exp(-z))) * 10) / 10;
  }

  function getRiskTier(ori) {
    if (ori < 15) return { label: "Clear / Low Risk", cls: "badge-clear", rgb: [22, 163, 74] };
    if (ori < 30) return { label: "Moderate Risk", cls: "badge-moderate", rgb: [202, 138, 4] };
    if (ori < 50) return { label: "Elevated Risk", cls: "badge-elevated", rgb: [234, 88, 12] };
    return { label: "High Risk", cls: "badge-high", rgb: [220, 38, 38] };
  }

  var api = { computeZ: computeZ, computeOri: computeOri, getRiskTier: getRiskTier };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  root.OdorModel = api;
})(typeof window !== "undefined" ? window : globalThis);
```

- [ ] **Step 2: Write the failing parity test**

Create `scratch/test_js_model.py`:

```python
import os
import sys
import json
import math
import shutil
import subprocess
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odor_forecast_core as core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_JS = os.path.join(ROOT, "docs", "model.js")


@unittest.skipIf(shutil.which("node") is None, "node not installed")
class TestJsParity(unittest.TestCase):
    def _js_ori(self, cell, coeffs, opts):
        script = (
            "const m=require(process.argv[1]);"
            "const a=JSON.parse(process.argv[2]);"
            "process.stdout.write(String(m.computeOri(a.cell,a.coeffs,a.opts)));"
        )
        payload = json.dumps({"cell": cell, "coeffs": coeffs, "opts": opts})
        out = subprocess.check_output(["node", "-e", script, MODEL_JS, payload])
        return float(out.decode().strip())

    def test_parity_aligned_and_misaligned(self):
        # Build a representative row; derive aligned from core, feed both sides identically.
        loc = "ZIP 42029 (Calvert City)"
        base = {
            "temperature": 78.0, "temperature_squared": 78.0 ** 2, "solar_radiation": 180.0,
            "relative_humidity": 72.0, "wind_speed": 2.5, "precipitation": 0.0,
            "diurnal_temperature_range": 18.0, "boundary_layer_height": 600.0,
            "atmospheric_pressure": 1005.0, "location": loc,
        }
        for wind_dir in (10.0, 200.0, 355.0):
            row = dict(base, wind_direction=wind_dir)
            aligned = core.check_wind_alignment(wind_dir, loc)
            cell = {
                "temp": row["temperature"], "temp_sq": row["temperature_squared"],
                "solar": row["solar_radiation"], "rh": row["relative_humidity"],
                "wind_speed": row["wind_speed"], "precip": row["precipitation"],
                "dtr": row["diurnal_temperature_range"], "blh": row["boundary_layer_height"],
                "pressure": row["atmospheric_pressure"], "aligned": bool(aligned),
            }
            opts = {"pressureOffset": core.PRESSURE_ELEVATION_OFFSET,
                    "windFilter": True, "penalty": 0.25, "boost": 1.0}
            ori_py = core.predict_ori(row, core.COEFFS_PITTSBURGH,
                                      use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0)
            ori_js = self._js_ori(cell, core.COEFFS_PITTSBURGH, opts)
            self.assertAlmostEqual(ori_py, ori_js, delta=0.1,
                                   msg=f"wind_dir={wind_dir} py={ori_py} js={ori_js}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the parity test — expect pass (or skip if no Node)**

Run: `.venv/bin/python -m pytest scratch/test_js_model.py -v`
Expected: `1 passed` (or `1 skipped` if `node` is not installed — in that case verify manually per Step 4).

- [ ] **Step 4: If Node is missing locally, sanity-check by hand**

Run: `.venv/bin/python -c "import odor_forecast_core as c; r={'temperature':78,'temperature_squared':6084,'solar_radiation':180,'relative_humidity':72,'wind_speed':2.5,'precipitation':0,'diurnal_temperature_range':18,'boundary_layer_height':600,'atmospheric_pressure':1005,'wind_direction':10,'location':'ZIP 42029 (Calvert City)'}; print(c.predict_ori(r,c.COEFFS_PITTSBURGH))"`
Record the value; it must equal what `model.js` `computeOri` yields for the same inputs (Node CI will enforce this).

- [ ] **Step 5: Commit**

```bash
git add docs/model.js scratch/test_js_model.py
git commit -m "feat: add docs/model.js client-side ORI math with python parity test"
```

---

## Task 4: `docs/index.html` + `docs/style.css` + `app.js` core (controls + 16-day grid)

**Files:**
- Create: `docs/index.html`, `docs/style.css`, `docs/app.js`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `docs/model.js` (`OdorModel`), `docs/data/{forecast,historical,meta}.json`.
- Produces (globals/functions in `app.js`, used by Tasks 5–6):
  - `APP.meta`, `APP.forecast`, `APP.historical` (loaded JSON)
  - `APP.activeCoeffs()` -> coefficients dict for the selected mode (incl. Custom)
  - `APP.opts()` -> `{pressureOffset, windFilter, penalty, boost}`
  - `APP.oriFor(cell)` -> number (calls `OdorModel.computeOri(cell, APP.activeCoeffs(), APP.opts())`)
  - `APP.onChange(cb)` registers a re-render callback fired whenever any control changes
  - `APP.switchTab(name)`; tab names `"map" | "forecast" | "monthly" | "report"`

- [ ] **Step 1: Add `docs/data/` to `.gitignore`**

Append to `.gitignore`:

```
# Generated forecast data (produced by generate_site.py / CI)
docs/data/
```

- [ ] **Step 2: Create `docs/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Calvert City Odor Risk Outlook</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header class="site-header">
    <div>
      <h1>Calvert City &amp; Surrounding Counties Odor Risk Outlook</h1>
      <p class="subtitle">Odor trapping forecasts for Marshall, McCracken &amp; Livingston Counties.</p>
    </div>
    <div class="source-meta">
      <span class="badge-pill badge-clear" id="source-badge">Loading…</span>
      <div class="updated" id="updated-stamp"></div>
    </div>
  </header>

  <div class="layout">
    <aside class="controls" id="controls">
      <h3>Parameters</h3>
      <label>Prediction Mode
        <select id="mode-select"></select>
      </label>
      <div id="custom-coeffs" class="custom-coeffs" hidden></div>
      <hr />
      <label class="toggle"><input type="checkbox" id="wind-filter" checked /> Wind Corridor Filter</label>
      <label>Penalty (Non-Corridor) <span id="penalty-val">75%</span>
        <input type="range" id="penalty" min="0" max="100" step="5" value="75" />
      </label>
      <label>Boost (Corridor-Aligned) <span id="boost-val">1.00</span>
        <input type="range" id="boost" min="1" max="3" step="0.05" value="1" />
      </label>
    </aside>

    <main class="content">
      <nav class="tabs">
        <button data-tab="map" class="tab active">🗺️ Map</button>
        <button data-tab="forecast" class="tab">📅 16-Day</button>
        <button data-tab="monthly" class="tab">📅 30-Day</button>
        <button data-tab="report" class="tab">📋 Report Odor</button>
      </nav>
      <section id="tab-map" class="tab-panel active"></section>
      <section id="tab-forecast" class="tab-panel">
        <label>Location
          <select id="forecast-loc"></select>
        </label>
        <div id="forecast-grid" class="card-grid"></div>
      </section>
      <section id="tab-monthly" class="tab-panel"></section>
      <section id="tab-report" class="tab-panel"></section>
    </main>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="model.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `docs/style.css`**

Port the Streamlit card/badge look. Minimum required classes: `.site-header`, `.layout`, `.controls`, `.content`, `.tabs`, `.tab`, `.tab.active`, `.tab-panel`, `.tab-panel.active` (use `display:none` for inactive panels), `.card-grid` (CSS grid, ~8 columns, wraps), `.clean-card`, `.badge-pill`, `.badge-clear`, `.badge-moderate`, `.badge-elevated`, `.badge-high`, `.calendar-grid` (7 columns), `.custom-coeffs`. Reuse the exact badge colors from `calvert_odor_forecaster.py` CSS block (`badge-clear`/`moderate`/`elevated`/`high`). Keep it plain CSS, no preprocessor.

```css
/* Representative core rules — fill in the remaining classes named above. */
* { box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; color: #0f172a; }
.site-header { display:flex; justify-content:space-between; align-items:flex-start; padding:1rem 1.5rem; border-bottom:1px solid #e2e8f0; }
.layout { display:flex; gap:1rem; padding:1rem 1.5rem; }
.controls { flex:0 0 250px; position:sticky; top:1rem; align-self:flex-start; }
.controls label { display:block; margin:0.6rem 0; font-size:0.85rem; }
.content { flex:1 1 auto; min-width:0; }
.tabs { display:flex; gap:1.5rem; border-bottom:1px solid #e2e8f0; margin-bottom:1rem; }
.tab { background:none; border:none; padding:0.5rem 0; cursor:pointer; opacity:0.6; font-weight:500; }
.tab.active { opacity:1; border-bottom:2px solid #0f172a; }
.tab-panel { display:none; }
.tab-panel.active { display:block; }
.card-grid { display:grid; grid-template-columns:repeat(8, 1fr); gap:0.5rem; }
@media (max-width: 1100px){ .card-grid{ grid-template-columns:repeat(4,1fr); } }
.calendar-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:0.5rem; }
.clean-card { background:rgba(128,128,128,0.08); border:1px solid rgba(128,128,128,0.15); border-radius:8px; padding:0.8rem; text-align:center; }
.badge-pill { display:inline-block; padding:0.25rem 0.6rem; font-size:0.72rem; font-weight:500; border-radius:4px; }
.badge-clear { background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }
.badge-moderate { background:#fefdf0; color:#854d0e; border:1px solid #fef08a; }
.badge-elevated { background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; }
.badge-high { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
#map { height:520px; border-radius:8px; }
```

- [ ] **Step 4: Create `docs/app.js` — bootstrap, controls, live recompute, 16-day grid**

```javascript
// Loads data + meta, wires the control panel, and renders tabs. ORI is computed
// live via OdorModel using whatever coefficients/options the controls select.
const APP = {
  meta: null, forecast: null, historical: null,
  _callbacks: [],
  onChange(cb) { this._callbacks.push(cb); },
  _fire() { this._callbacks.forEach(function (cb) { cb(); }); },
  mode() { return document.getElementById("mode-select").value; },
  activeCoeffs() {
    if (this.mode() === "custom") return this._customCoeffs();
    return this.meta.coeffs[this.mode()];
  },
  _customCoeffs() {
    var c = {};
    Object.keys(this.meta.custom_slider_ranges).forEach(function (k) {
      c[k] = parseFloat(document.getElementById("cc-" + k).value);
    });
    return c;
  },
  opts() {
    return {
      pressureOffset: this.meta.pressure_offset,
      windFilter: document.getElementById("wind-filter").checked,
      penalty: 1 - (parseFloat(document.getElementById("penalty").value) / 100),
      boost: parseFloat(document.getElementById("boost").value),
    };
  },
  oriFor(cell) { return OdorModel.computeOri(cell, this.activeCoeffs(), this.opts()); },
};

async function loadJSON(path) { const r = await fetch(path); if (!r.ok) throw new Error(path); return r.json(); }

function buildModeSelect() {
  var sel = document.getElementById("mode-select");
  Object.keys(APP.meta.mode_labels).forEach(function (key) {
    var o = document.createElement("option"); o.value = key; o.textContent = APP.meta.mode_labels[key];
    sel.appendChild(o);
  });
  var custom = document.createElement("option"); custom.value = "custom"; custom.textContent = "Custom (manual)";
  sel.appendChild(custom);
  sel.value = "estimated_calvert";
}

function buildCustomCoeffSliders() {
  var box = document.getElementById("custom-coeffs");
  var ranges = APP.meta.custom_slider_ranges;
  var defaults = APP.meta.coeffs.estimated_calvert;
  Object.keys(ranges).forEach(function (k) {
    var r = ranges[k];
    var wrap = document.createElement("label");
    wrap.style.fontSize = "0.78rem";
    wrap.innerHTML = k + ' <input type="range" id="cc-' + k + '" min="' + r[0] + '" max="' + r[1] +
      '" step="' + r[2] + '" value="' + defaults[k] + '">';
    box.appendChild(wrap);
  });
}

function wireControls() {
  var ids = ["mode-select", "wind-filter", "penalty", "boost"];
  ids.forEach(function (id) {
    document.getElementById(id).addEventListener("input", function () {
      document.getElementById("custom-coeffs").hidden = (APP.mode() !== "custom");
      document.getElementById("penalty-val").textContent = document.getElementById("penalty").value + "%";
      document.getElementById("boost-val").textContent = parseFloat(document.getElementById("boost").value).toFixed(2);
      APP._fire();
    });
  });
  document.getElementById("custom-coeffs").addEventListener("input", function () { APP._fire(); });
}

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("active", t.dataset.tab === name); });
  document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.toggle("active", p.id === "tab-" + name); });
  if (APP._onTab) APP._onTab(name);
}
APP.switchTab = setActiveTab;

function renderForecastGrid() {
  var loc = document.getElementById("forecast-loc").value;
  var grid = document.getElementById("forecast-grid");
  grid.innerHTML = "";
  APP.forecast.dates.forEach(function (d) {
    var cell = APP.forecast.features[d][loc];
    if (!cell) return;
    var ori = APP.oriFor(cell);
    var tier = OdorModel.getRiskTier(ori);
    var rgb = "rgb(" + tier.rgb.join(",") + ")";
    var dt = new Date(d + "T00:00:00");
    var card = document.createElement("div");
    card.className = "clean-card";
    card.innerHTML =
      '<div style="font-weight:600;font-size:0.8rem;">' + dt.toLocaleDateString(undefined, {weekday:"short"}) + '</div>' +
      '<div style="font-size:0.7rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month:"short", day:"numeric"}) + '</div>' +
      '<div style="font-size:1.5rem;font-weight:700;color:' + rgb + ';margin:0.3rem 0;">' + ori.toFixed(1) + '%</div>' +
      '<span class="badge-pill ' + tier.cls + '">' + tier.label + '</span>';
    grid.appendChild(card);
  });
}

function buildForecastLocSelect() {
  var sel = document.getElementById("forecast-loc");
  APP.forecast.locations.forEach(function (l) {
    var o = document.createElement("option"); o.value = l.zip; o.textContent = l.zip + " — " + l.name;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderForecastGrid);
}

async function main() {
  APP.meta = await loadJSON("data/meta.json");
  APP.forecast = await loadJSON("data/forecast.json");
  APP.historical = await loadJSON("data/historical.json");

  document.getElementById("source-badge").textContent = "🟢 Source: " + APP.meta.source;
  document.getElementById("updated-stamp").textContent = "Updated: " + APP.meta.generated_utc;

  buildModeSelect();
  buildCustomCoeffSliders();
  buildForecastLocSelect();
  wireControls();

  document.querySelectorAll(".tab").forEach(function (t) {
    t.addEventListener("click", function () { setActiveTab(t.dataset.tab); });
  });

  APP.onChange(renderForecastGrid);
  renderForecastGrid();
  if (APP._initTabs) APP._initTabs();   // map/monthly/report hooks (Tasks 5–6)
}

main().catch(function (e) { document.body.insertAdjacentHTML("afterbegin", '<p style="color:red;padding:1rem;">Failed to load: ' + e.message + " (run generate_site.py first)</p>"); });
```

- [ ] **Step 5: Generate data and verify the page loads with a live grid**

Run: `.venv/bin/python generate_site.py` (skip if `docs/data/forecast.json` already exists from Task 2).
Then open the page over a local server (file:// blocks `fetch`):
Run: `.venv/bin/python -m http.server 8765 --directory docs` (background), then open `http://localhost:8765/`.
Expected (manual): header shows source + timestamp; the **16-Day** tab shows a grid of risk cards; moving **Penalty**/**Boost** sliders and switching **Mode** to "Custom" updates the card percentages live. Stop the server (`Ctrl-C`) when done.

- [ ] **Step 6: Commit**

```bash
git add docs/index.html docs/style.css docs/app.js .gitignore
git commit -m "feat: static page shell with live controls and 16-day forecast grid"
```

---

## Task 5: Leaflet map tab with live polygon recolor + Layers control scaffold

**Files:**
- Modify: `docs/app.js`

**Interfaces:**
- Consumes: `APP` (Task 4), `data/calvert_zips.geojson`, `OdorModel`.
- Produces: `renderMap()`, `APP._mapState` (Leaflet map + geojson layer handles); registers a map renderer on the `map` tab and `APP.onChange`.

- [ ] **Step 1: Add the map tab renderer to `app.js`**

Insert before `main()`:

```javascript
APP._mapState = { map: null, geo: null, geojson: null, dateSel: null, layersBox: null };

function mapPanelScaffold() {
  var panel = document.getElementById("tab-map");
  panel.innerHTML =
    '<div class="map-toolbar">' +
    '  <label>Date <select id="map-date"></select></label>' +
    '  <fieldset class="layers"><legend>Layers</legend>' +
    '    <label><input type="checkbox" id="layer-risk" checked> Risk</label>' +
    '    <label title="Coming soon"><input type="checkbox" id="layer-plume" disabled> Plume</label>' +
    '    <label title="Coming soon"><input type="checkbox" id="layer-reports" disabled> Reports</label>' +
    '  </fieldset>' +
    '</div><div id="map"></div>';
  var sel = panel.querySelector("#map-date");
  APP.forecast.dates.forEach(function (d, i) {
    var o = document.createElement("option"); o.value = d; o.textContent = d; if (i === 1) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderMap);
  panel.querySelector("#layer-risk").addEventListener("change", renderMap);
  APP._mapState.dateSel = sel;
}

async function ensureMap() {
  if (APP._mapState.map) return;
  var IND = [37.0486, -88.3480];
  var map = L.map("map").setView([IND[0] - 0.05, IND[1]], 10);
  L.tileLayer("https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap, © CARTO", maxZoom: 19 }).addTo(map);
  L.circleMarker(IND, { radius: 9, color: "#475569", fillColor: "#64748b", fillOpacity: 0.9 })
    .bindTooltip("Calvert City Industrial Complex (Source)").addTo(map);
  APP._mapState.map = map;
  APP._mapState.geojson = await loadJSON("calvert_zips.geojson");
}

function renderMap() {
  if (!APP._mapState.map) return;
  var ms = APP._mapState;
  var date = ms.dateSel.value;
  var showRisk = document.getElementById("layer-risk").checked;
  if (ms.geo) { ms.map.removeLayer(ms.geo); ms.geo = null; }
  if (!showRisk) return;
  var feats = APP.forecast.features[date] || {};
  ms.geo = L.geoJSON(ms.geojson, {
    style: function (f) {
      var cell = feats[f.properties.zip];
      if (!cell) return { color: "#94a3b8", weight: 1, fillColor: "#cbd5e1", fillOpacity: 0.2 };
      var tier = OdorModel.getRiskTier(APP.oriFor(cell));
      return { color: "#475569", weight: 1.5, fillColor: "rgb(" + tier.rgb.join(",") + ")", fillOpacity: 0.45 };
    },
    onEachFeature: function (f, layer) {
      var cell = feats[f.properties.zip];
      var ori = cell ? APP.oriFor(cell) : null;
      var tier = cell ? OdorModel.getRiskTier(ori) : { label: "N/A" };
      layer.bindTooltip("ZIP " + f.properties.zip + "<br>ORI: " +
        (ori === null ? "N/A" : ori.toFixed(1) + "%") + "<br>" + tier.label);
    },
  }).addTo(ms.map);
}
```

- [ ] **Step 2: Hook the map into tab switching and live updates**

In `main()`, replace the `if (APP._initTabs) APP._initTabs();` line with explicit wiring:

```javascript
  mapPanelScaffold();
  APP._onTab = async function (name) {
    if (name === "map") { await ensureMap(); setTimeout(function () { APP._mapState.map.invalidateSize(); renderMap(); }, 50); }
  };
  APP.onChange(function () { if (APP._mapState.map) renderMap(); });
  // initialize the map immediately if Map is the default tab
  await ensureMap(); renderMap();
```

(Leaflet needs `invalidateSize()` after the panel becomes visible, hence the tab hook.)

- [ ] **Step 3: Add minimal toolbar CSS**

Append to `docs/style.css`:

```css
.map-toolbar { display:flex; gap:1.5rem; align-items:center; margin-bottom:0.6rem; flex-wrap:wrap; }
.map-toolbar .layers { display:flex; gap:0.8rem; border:1px solid #e2e8f0; border-radius:6px; padding:0.2rem 0.6rem; }
.map-toolbar .layers legend { font-size:0.7rem; opacity:0.6; }
```

- [ ] **Step 4: Verify the map renders and recolors live**

Run: `.venv/bin/python -m http.server 8765 --directory docs`, open `http://localhost:8765/`, click **🗺️ Map**.
Expected (manual): ZIP polygons render colored by risk; the gray source marker shows; changing the **Date** dropdown and the **Penalty/Boost/Mode** controls recolors polygons live; hover tooltips show ORI. The Plume/Reports layer checkboxes are present but disabled.

- [ ] **Step 5: Commit**

```bash
git add docs/app.js docs/style.css
git commit -m "feat: Leaflet risk map with live recolor and layers scaffold"
```

---

## Task 6: 30-day calendar tab + Report tab (geolocation → Google Form)

**Files:**
- Modify: `docs/app.js`, `docs/index.html` (Google Form config block)

**Interfaces:**
- Consumes: `APP.historical`, `OdorModel`, `navigator.geolocation`.
- Produces: `renderMonthly()`, `renderReportTab()`; a `GOOGLE_FORM` config object.

- [ ] **Step 1: Add the Google Form config to `index.html`**

Just before `<script src="model.js">`, add:

```html
  <script>
    // Swap these for your real Google Form. Pre-fill entry IDs come from the form's
    // "Get pre-filled link" feature (one per field).
    window.GOOGLE_FORM = {
      viewUrl: "https://docs.google.com/forms/d/e/REPLACE_WITH_FORM_ID/viewform",
      latEntry: "entry.0000000001",
      lonEntry: "entry.0000000002"
    };
  </script>
```

- [ ] **Step 2: Add the 30-day calendar renderer to `app.js`**

Insert before `main()`:

```javascript
function renderMonthly() {
  var panel = document.getElementById("tab-monthly");
  if (!panel.querySelector("#monthly-loc")) {
    panel.innerHTML =
      '<label>Location <select id="monthly-loc"></select></label>' +
      '<div class="calendar-head"></div><div id="calendar" class="calendar-grid"></div>';
    var sel = panel.querySelector("#monthly-loc");
    APP.historical.locations.forEach(function (l) {
      var o = document.createElement("option"); o.value = l.zip; o.textContent = l.zip + " — " + l.name; sel.appendChild(o);
    });
    sel.addEventListener("change", renderMonthly);
    var head = panel.querySelector(".calendar-head");
    head.className = "calendar-grid calendar-head";
    ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].forEach(function (d) {
      var c = document.createElement("div"); c.textContent = d; c.style.fontWeight = "600"; c.style.textAlign = "center"; head.appendChild(c);
    });
  }
  var loc = panel.querySelector("#monthly-loc").value;
  var cal = panel.querySelector("#calendar");
  cal.innerHTML = "";
  var dates = APP.historical.dates;
  var firstWeekday = (new Date(dates[0] + "T00:00:00").getDay() + 6) % 7; // Mon=0
  for (var i = 0; i < firstWeekday; i++) { var pad = document.createElement("div"); cal.appendChild(pad); }
  dates.forEach(function (d) {
    var cell = APP.historical.features[d][loc];
    var div = document.createElement("div");
    div.className = "clean-card";
    if (cell) {
      var ori = APP.oriFor(cell);
      var tier = OdorModel.getRiskTier(ori);
      var dt = new Date(d + "T00:00:00");
      div.innerHTML =
        '<div style="font-size:0.7rem;opacity:0.6;">' + dt.toLocaleDateString(undefined,{month:"short",day:"numeric"}) + '</div>' +
        '<div style="font-size:1.2rem;font-weight:700;color:rgb(' + tier.rgb.join(",") + ');">' + ori.toFixed(1) + '%</div>' +
        '<span class="badge-pill ' + tier.cls + '" title="Wind ' + cell.wind_speed.toFixed(1) + ' mph @ ' +
        Math.round(cell.wind_dir) + '°, PBLH ' + Math.round(cell.blh) + ' ft, Rain ' + cell.precip.toFixed(2) + ' in">' +
        tier.label.split(" ")[0] + '</span>';
    }
    cal.appendChild(div);
  });
}
```

- [ ] **Step 3: Add the Report tab renderer (geolocation → pre-filled Google Form)**

Insert before `main()`:

```javascript
function buildFormUrl(lat, lon) {
  var f = window.GOOGLE_FORM;
  var u = new URL(f.viewUrl);
  if (lat != null && lon != null) {
    u.searchParams.set(f.latEntry, lat.toFixed(6));
    u.searchParams.set(f.lonEntry, lon.toFixed(6));
  }
  return u.href;
}

function renderReportTab() {
  var panel = document.getElementById("tab-report");
  if (panel.dataset.built) return;
  panel.dataset.built = "1";
  panel.innerHTML =
    '<div class="clean-card" style="text-align:left;max-width:560px;">' +
    '<h3>Report an Odor</h3>' +
    '<p>Optionally share your location so we can map where odors are reported.</p>' +
    '<div id="geo-status" style="font-size:0.85rem;opacity:0.7;">Location not set.</div>' +
    '<div style="margin:0.6rem 0;display:flex;gap:0.5rem;flex-wrap:wrap;">' +
    '  <button id="btn-geo">📍 Get My Location</button>' +
    '  <button id="btn-geo-skew">🛡️ Skewed (Privacy)</button>' +
    '</div>' +
    '<a id="open-form" class="form-link" href="' + buildFormUrl(null, null) + '" target="_blank" rel="noopener">Open Report Form →</a>' +
    '</div>';

  var state = { lat: null, lon: null };
  function setStatus(msg) { panel.querySelector("#geo-status").textContent = msg; }
  function refreshLink() { panel.querySelector("#open-form").href = buildFormUrl(state.lat, state.lon); }

  function grab(skew) {
    if (!navigator.geolocation) { setStatus("Geolocation not supported by this browser."); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      if (skew) { lat += (Math.random() * 0.004) - 0.002; lon += (Math.random() * 0.004) - 0.002; }
      state.lat = lat; state.lon = lon;
      setStatus((skew ? "Skewed" : "Exact") + " location set: " + lat.toFixed(5) + ", " + lon.toFixed(5));
      refreshLink();
    }, function (err) { setStatus("Location error: " + err.message); }, { enableHighAccuracy: true, timeout: 10000 });
  }
  panel.querySelector("#btn-geo").addEventListener("click", function () { grab(false); });
  panel.querySelector("#btn-geo-skew").addEventListener("click", function () { grab(true); });
}
```

- [ ] **Step 4: Wire the two new tabs into the tab hook in `main()`**

Update `APP._onTab` (added in Task 5) to also render monthly/report:

```javascript
  APP._onTab = async function (name) {
    if (name === "map") { await ensureMap(); setTimeout(function () { APP._mapState.map.invalidateSize(); renderMap(); }, 50); }
    if (name === "monthly") renderMonthly();
    if (name === "report") renderReportTab();
  };
  APP.onChange(function () {
    if (document.getElementById("tab-monthly").classList.contains("active")) renderMonthly();
  });
```

- [ ] **Step 5: Add a small `.form-link` style**

Append to `docs/style.css`:

```css
.form-link { display:inline-block; margin-top:0.6rem; padding:0.5rem 0.9rem; background:#0f172a; color:#fff; border-radius:6px; text-decoration:none; }
button { padding:0.4rem 0.7rem; border:1px solid #cbd5e1; border-radius:6px; background:#fff; cursor:pointer; }
```

- [ ] **Step 6: Verify both tabs**

Run: `.venv/bin/python -m http.server 8765 --directory docs`, open `http://localhost:8765/`.
Expected (manual): **30-Day** tab shows a Mon–Sun calendar of historical risk that recolors when controls change; hovering a badge shows wind/PBLH/rain. **Report Odor** tab: clicking "Get My Location" prompts the browser, fills the status line, and the "Open Report Form" link gains `?entry.…=lat&…=lon` (verify by right-click → copy link). Form opens in a new tab.

- [ ] **Step 7: Commit**

```bash
git add docs/app.js docs/index.html docs/style.css
git commit -m "feat: 30-day calendar and geolocation-prefilled report tab"
```

---

## Task 7: GitHub Actions daily cron + Pages deploy + DEPLOYMENT.md

**Files:**
- Create: `.github/workflows/forecast.yml`, `DEPLOYMENT.md`

**Interfaces:**
- Consumes: `generate_site.py`, `docs/`.
- Produces: a scheduled workflow that regenerates data and deploys `docs/` to GitHub Pages.

- [ ] **Step 1: Create `.github/workflows/forecast.yml`**

```yaml
name: Daily Odor Forecast

on:
  schedule:
    - cron: "0 6 * * *"   # 06:00 UTC ≈ 1 AM Central, daily
  workflow_dispatch: {}

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install requests pandas numpy
      - name: Generate forecast data
        run: python generate_site.py
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs
      - name: Deploy to GitHub Pages
        id: deploy
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/forecast.yml')); print('yaml OK')"`
Expected: `yaml OK`. (If `yaml` is missing: `.venv/bin/pip install pyyaml` first.)

- [ ] **Step 3: Create `DEPLOYMENT.md`**

```markdown
# Deployment

## GitHub Pages (primary)

1. Push the `static-forecast-site` branch and open a PR / merge to `main`.
2. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. The `Daily Odor Forecast` workflow runs every day at 06:00 UTC and on demand
   (Actions tab → *Daily Odor Forecast* → **Run workflow**).
4. The published site URL appears in the workflow's `deploy` step output.

Data in `docs/data/` is generated by CI each run and is **not** committed
(see `.gitignore`). If Open-Meteo is unreachable, `generate_site.py` exits
non-zero and the deploy is skipped, so the last good site stays live.

## University / home server (later)

`generate_site.py` is server-agnostic. Example crontab writing into a web root:

    0 1 * * *  cd /srv/odor && /srv/odor/.venv/bin/python generate_site.py >> /var/log/odor.log 2>&1

Point your web server (nginx/Apache) at the `docs/` directory. The page is fully
static; only `docs/data/*.json` changes each run.

## Local preview

    .venv/bin/python generate_site.py
    .venv/bin/python -m http.server 8765 --directory docs
    # open http://localhost:8765/   (file:// won't work — fetch() needs http)
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/forecast.yml DEPLOYMENT.md
git commit -m "ci: daily cron + GitHub Pages deploy for static forecast site"
```

- [ ] **Step 5: Final full-suite verification**

Run: `.venv/bin/python -m pytest scratch/test_forecast_engine.py scratch/test_generate_site.py scratch/test_js_model.py -v`
Expected: all pass (the JS parity test may show `skipped` if Node is absent locally; it runs in CI).

---

## Self-Review Notes (addressed)

- **Spec coverage:** core extraction (T1), generator + JSON schema (T2), client-side model incl. Custom mode (T3), page shell + controls + 16-day (T4), Leaflet map + Layers scaffold (T5), 30-day calendar + Report/Google-Form geolocation (T6), Actions cron + Pages + university-server notes + resilience (T7). Plume/reports layers are explicitly scaffolded-only (disabled checkboxes) per the spec's "future, not this build."
- **Type consistency:** `cell` keys (`temp, temp_sq, solar, rh, wind_speed, wind_dir, precip, dtr, blh, pressure, aligned`) are identical across `generate_site.build_feature_payload`, `model.js`, the parity test, and all `app.js` renderers. `opts` keys (`pressureOffset, windFilter, penalty, boost`) match between `APP.opts()`, `model.js computeOri`, and the parity test. Mode keys (`estimated_calvert`, `exact_pittsburgh`, `custom`) match between `meta.json`, `buildModeSelect`, and `activeCoeffs`.
- **No placeholders:** the only intentional fill-in is `window.GOOGLE_FORM` (the user must paste their real form ID/entry IDs — documented as such) and the verbatim copy of `check_wind_alignment`'s body from the existing file (explicitly instructed to copy, not retype).
```
