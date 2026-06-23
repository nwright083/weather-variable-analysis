# Design: Static Daily-Generated Odor Risk Forecast Website

> Date: 2026-06-23
> Status: Approved (design) — pending implementation plan
> Related: `calvert_odor_forecaster.py` (existing Streamlit app), `CALVERT_FORECASTER_REVIEW.md`

## Context & Goal

The Calvert City Odor Risk forecaster currently exists only as a Streamlit app that requires a
live Python runtime. The goal is a **static website** that:

- Regenerates once daily via a cron job (GitHub Actions first; portable to a university/home server later).
- Deploys to **GitHub Pages** with no server at serve time.
- Shows the 16-day ORI forecast, 30-day historical calendar, and an interactive map.
- Keeps the **same interactive controls as the Streamlit sidebar** (prediction mode incl. Custom,
  wind-corridor filter, penalty %, boost) — all client-side.
- Is built layer-first so **plume analysis** and **odor reports** can be added later as additive map
  layers without reworking the forecast pipeline.

This is a first test deployment. Privacy/scale hardening is out of scope for now.

## Approach (chosen: Option B)

**Python data generator + static HTML/JS shell.** Python fetches weather and does the daily
aggregation only; **all ORI math runs in the browser** from raw weather features + core-exported
coefficients. This makes Custom mode and the wind sliders fully live, and keeps the JSON small
(no per-mode duplication).

Rejected: Option A (single self-contained HTML — becomes unmaintainable as layers are added);
Option C (Jekyll/Hugo — framework overhead unsuited to a data-driven dashboard).

## Architecture & File Layout

```
weather-varaible-analysis/
├── odor_forecast_core.py        # NEW — pure logic, zero Streamlit:
│                                #   COEFFS_PITTSBURGH, COEFFS_EST_CALVERT,
│                                #   PRESSURE_ELEVATION_OFFSET, calculate_bearing,
│                                #   check_wind_alignment, predict_ori, get_risk_meta,
│                                #   fetch_forecasts, fetch_historical_weather, daily aggregation
├── calvert_odor_forecaster.py   # REFACTORED — imports from core; keeps only Streamlit UI
│                                #   (sidebar, tabs, tester-dispatch DB panel)
├── generate_site.py             # NEW — headless cron entry point; writes docs/data/*.json
├── docs/                        # GitHub Pages serves this folder
│   ├── index.html               #   static shell (committed once)
│   ├── app.js                   #   tabs, Leaflet map, live model math, geolocation→form
│   ├── style.css                #   reuses Streamlit card/badge look
│   ├── calvert_zips.geojson     #   copied from repo root at generation time
│   └── data/                    #   regenerated daily:
│       ├── forecast.json        #     16-day raw weather features per cell
│       ├── historical.json      #     30-day raw weather features per cell
│       └── meta.json            #     coeffs, pressure_offset, slider ranges, timestamp, source
├── .github/workflows/forecast.yml  # NEW — daily cron + Pages deploy
├── DEPLOYMENT.md                # NEW — one-time GitHub Pages setup + university-server crontab
└── scratch/test_*.py            # tests target core; new JS-parity + generator smoke tests
```

**Core extraction refactor:** move the listed functions out of `calvert_odor_forecaster.py` into
`odor_forecast_core.py`. The Streamlit-global reads inside `predict_ori`
(`use_wind_filter`, `wind_penalty`, `wind_boost`) become **explicit function arguments**. The
Streamlit app and `generate_site.py` both import from core — single source of truth for the model,
coefficients, and the four recent methodology fixes (pressure offset, vector wind mean, history
recency, log-odds wind adjustment).

## Data Flow

```
generate_site.py (daily):
  core.fetch_forecasts(LOCATIONS)          -> 16-day daily-aggregated weather
  core.fetch_historical_weather(LOCATIONS) -> 30-day daily-aggregated weather (past_days endpoint)
  for each location × day:
      compute aligned flag (core.check_wind_alignment)
      emit raw model features (no ORI — JS computes it)
  copy calvert_zips.geojson -> docs/
  write docs/data/{forecast,historical,meta}.json
```

The generator does NOT compute ORI. It emits raw features; the browser computes `z` and ORI for
the active coefficient set.

## JSON Schemas

`forecast.json` (and `historical.json`, identical with 30 dates):

```json
{
  "dates": ["2026-06-24", "..."],
  "locations": [{"zip": "42029", "name": "Calvert City", "lat": 37.0317, "lon": -88.3542}],
  "features": {
    "2026-06-24": {
      "42029": {
        "aligned": true,
        "temp": 78.1, "temp_sq": 6099.6, "solar": 182.0, "rh": 71.5,
        "wind_speed": 3.2, "wind_dir": 12, "precip": 0.0, "dtr": 16.4,
        "blh": 640, "pressure": 1005.2
      }
    }
  }
}
```

`meta.json` (single source of truth for model constants, exported from core):

```json
{
  "generated_utc": "2026-06-24T06:00:00Z",
  "source": "Open-Meteo (NWP + ERA5)",
  "pressure_offset": 17.4,
  "coeffs": {
    "estimated_calvert": {"const": 18.0, "temperature": 0.114354, "...": "..."},
    "exact_pittsburgh":  {"const": 17.415789, "...": "..."}
  },
  "mode_labels": {"estimated_calvert": "Estimated Calvert City", "exact_pittsburgh": "Exact Pittsburgh Model"},
  "custom_slider_ranges": {"const": [-30, 30, 0.1], "temperature": [-0.5, 0.5, 0.001], "...": "..."},
  "wind_defaults": {"filter": true, "penalty_pct": 75, "boost": 1.0}
}
```

## Client-Side Model (app.js)

Replicates `predict_ori` exactly, driven by `meta.json` coefficients:

```js
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
function computeOri(cell, c, opts) {           // opts: {pressureOffset, windFilter, penalty, boost}
  let z = computeZ(cell, c, opts.pressureOffset);
  if (opts.windFilter) z += cell.aligned ? Math.log(opts.boost) : Math.log(Math.max(opts.penalty, 1e-9));
  z = Math.max(-60, Math.min(60, z));
  return 100 / (1 + Math.exp(-z));
}
// tier via thresholds 15 / 30 / 50 -> [clear, moderate, elevated, high] (mirrors core.get_risk_meta)
```

Controls: Mode select (Estimated Calvert / Exact Pittsburgh / Custom-with-coeff-sliders),
wind filter checkbox, penalty slider (0–100%, → factor `1 - pct/100`), boost slider (1.0–3.0).
Every control change re-runs `computeOri` for all visible cells and recolors map + cards instantly.

## Page Structure

Single `index.html`, vanilla-JS tabs (no framework), Leaflet from CDN:

- **Map tab** — Leaflet + `calvert_zips.geojson`; polygon fill recomputed live; hover tooltip
  (ORI / tier / wind), industrial source marker; date dropdown (16 forecast dates, default tomorrow).
  Includes a **Layers control** (checkboxes: Risk / Plume / Reports) shipping with only Risk active.
- **16-Day tab** — grid of risk cards (mirrors the Streamlit 2×8 look) for a selected location.
- **30-Day tab** — Mon–Sun aligned historical calendar with per-day details popover.
- **Report tab** — "📍 Get My Location" + privacy-skew buttons (existing `navigator.geolocation` JS) →
  "Open Report Form" launches a **pre-filled Google Form** (lat/lon as `entry.*` query params) in a
  new tab. Form ID lives in a config block in `app.js` to be swapped for the real form.

## Deployment

`.github/workflows/forecast.yml`:
- `on.schedule: '0 6 * * *'` (≈1 AM Central) + `workflow_dispatch`.
- Steps: checkout → setup-python 3.11 + `pip install requests pandas numpy` → `python generate_site.py`
  → upload `docs/` Pages artifact → deploy-pages.
- **Resilience:** if Open-Meteo fails, `generate_site.py` exits non-zero; workflow fails without
  overwriting last-good JSON (site keeps showing prior forecast). The core mock fallback is for
  **local dev only**, never deployed.
- One-time: repo Settings → Pages → source "GitHub Actions" (documented in `DEPLOYMENT.md`).
- University/home server later: plain crontab line runs the same `generate_site.py` into the web root.

Dev loop: `python generate_site.py && open docs/index.html` — no Actions required to test.

## Testing

1. **Core parity** — existing 5 tests retargeted to `odor_forecast_core`; keep passing (guards the refactor).
2. **JS/Python agreement** — Python computes ORI for sample cells; a test asserts the documented JS
   formula (replicated in the test harness) agrees to ≤0.1 ORI.
3. **Generator smoke test** — run `generate_site.py` against a mocked Open-Meteo response; assert the
   three JSON files are written with expected keys/schema.
4. **Manual** — generate + open page; verify four tabs, live slider recolor, geolocation→form prefill.

## Extensibility (Future, not this build)

- **Plume analysis** → `docs/data/plume.json` (GeoJSON contours / deposition overlay) as a toggleable
  Leaflet layer; `generate_site.py` gains a `fetch_plume()` in its data-sources section.
- **Odor reports** → `docs/data/reports.json` (exported from the Google Sheet, later a DB) as severity-
  colored point markers; toggleable layer.
- The Layers control and the generator's data-sources structure exist from day one, so both are purely
  additive.

## Out of Scope

- Real-time report ingestion / backend DB (Google Form + Sheet covers reports for now).
- Auth / private deployment (test is public on GitHub Pages).
- Louisville prediction mode (tracked separately in `FUTURE_IDEAS.md` item 1a; design supports it as a
  one-coefficient-dict addition).
```
