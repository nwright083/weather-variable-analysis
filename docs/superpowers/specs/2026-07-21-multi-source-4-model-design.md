# Odor Forecaster: 4-Model Restructure + Multi-Source Proximity

**Date:** 2026-07-21
**Status:** Approved (design), pending implementation

## Goal

1. Make the **Proximity-Enhanced** model the deployed default (conservative, most discriminating), keeping all models one click away.
2. Expose the Pittsburgh→Calvert **pressure/elevation transfer offset** as an explicit modeling axis instead of a hidden always-on transform, so "Exact" is honestly exact.
3. Add a **second odor source** (TVA Shawnee Fossil Plant) and generalize the proximity model from single-source to **summed multi-source** exposure.

## Model set — a 2×2 (all four selectable)

Two axes: **input transfer** (pressure offset off/on) × **spatial** (weather-only / proximity).

| # | Model | Coefficients | Pressure offset | Proximity |
|---|-------|--------------|:---:|:---:|
| 1 | Exact Pittsburgh | `COEFFS_PITTSBURGH` | off | — |
| 2 | Exact Pittsburgh + Proximity | `COEFFS_PITTSBURGH_PROXIMITY` | off | ✓ |
| 3 | Pittsburgh Transfer | `COEFFS_PITTSBURGH` | on | — |
| 4 | **Pittsburgh Transfer + Proximity** *(default)* | `COEFFS_PITTSBURGH_PROXIMITY` | on | ✓ |

- The **only** toggle between an Exact model and its Transfer twin is the 17.4 hPa pressure offset.
- BLH unit-normalization and de-biasing remain **always on** (correctness, not a Calvert choice). A UI footnote states this so "Exact" is not over-claimed.
- The pressure offset is a ~+0.8 pt uniform nudge (constant z-shift); it does not change day-to-day ranking. The split exists for scientific honesty and as a home for future, quantifiable Calvert corrections.

## Multi-source proximity (summation)

Sources defined in **one list** in `odor_forecast_core.py`:

```python
ODOR_SOURCES = [
    {"name": "Calvert City Industrial Complex", "lat": 37.0486, "lon": -88.3480},
    {"name": "TVA Shawnee Fossil Plant",        "lat": 37.15,   "lon": -88.77},  # verify at build
]
```

Per tract per day, `generate_site.py` precomputes two scalar aggregates and stores them in the JSON payload so `docs/model.js` stays a thin consumer and Python↔JS parity holds:

- **Exposure** `E = Σ_i exp(-0.02 · d_i)` over sources (miles; k=0.02 unchanged).
- **Wind alignment** `A = Σ_i [exp(-0.02 · d_i) · align_i] / Σ_i exp(-0.02 · d_i)` — exposure-weighted mean of per-source continuous alignment, so the wind term reflects whichever sources dominate exposure.

`predict_ori` consumes `E` via `multi_source_exposure` coeff and `A` via `wind_align_weighted` coeff (coefficients +1.727589 / +1.377858 reused as-is). Summation moves Calvert's exposure scale closer to the multi-emitter Pittsburgh training construction — more faithful, not less.

## Code touch-points

- **`odor_forecast_core.py`**: add `ODOR_SOURCES`; add helpers to compute summed exposure + exposure-weighted alignment for a location; add `apply_pressure_transfer: bool` param to `predict_ori` (default True) gating the offset; consume precomputed `E`/`A`.
- **`docs/model.js`**: mirror the pressure-transfer flag and the (already-aggregated) `E`/`A` consumption.
- **`generate_site.py`**: build **4** model configs (coeffs × offset flag); precompute `E`/`A` per tract/day into forecast/historical/hourly payloads; set `default_mode = "pittsburgh_transfer_proximity"`.
- **`docs/data/meta.json`**: 4 modes + labels + default (regenerated).
- **`docs/app.js`**: labels, descriptions, methodology tables/curves, and footnote for 4 models.
- **Tests**: `scratch/test_js_model.py` (parity with multi-source + 4 models), `scratch/test_forecast_engine.py` (multi-source math, offset flag).

## Model keys / labels

| key | label |
|-----|-------|
| `exact_pittsburgh` | Exact Pittsburgh |
| `exact_pittsburgh_proximity` | Exact Pittsburgh + Proximity |
| `pittsburgh_transfer` | Pittsburgh Transfer |
| `pittsburgh_transfer_proximity` | Pittsburgh Transfer + Proximity |

## Report update (separate repo — edit only)

Update `/Users/nawrig04/plume-validation/REPORT.md` Part II: deployed default is now Transfer+Proximity; document the 2×2; add Shawnee as a second source in Finding 5; frame the pressure offset as the Exact↔Transfer axis. **Do not commit or push plume-validation** (per user).

## Delivery

- Regenerate `docs/data/` from live weather, verify parity + suite pass.
- Commit + push **only** `weather-varaible-analysis` (updates the live site). REPORT.md edited but left uncommitted.

## Out of scope / YAGNI

- Decomposing the Calvert cluster into individual TRI facilities (offered, declined — cluster centroid retained).
- A Paducah riverfront point (declined — no defensible TRI air emitter).
- Emission-weighted source magnitudes (coefficient handles magnitude; equal-weight point sources kept).
