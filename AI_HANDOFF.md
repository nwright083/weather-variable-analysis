# Project Handoff: Odor Complaint Weather Variable Analysis
> **For Claude Code and Gemini pair programmers.**
> This is a living synchronization document. Please review it before starting work and update it at the end of each session to keep context aligned across different AI agents.

---

## 📌 Project Overview
This project investigates the relationship between daily and hourly odor complaints (publicly reported in Pittsburgh, PA via the SmellPGH app, and in Louisville, KY via the LMAPCD agency) and local meteorological variables (temperature, relative humidity, boundary layer height, wind speed, wind direction, diurnal temperature range, etc.).

Key goals:
* Quantify how meteorological variables (specifically boundary layer height and diurnal temperature range) affect the likelihood and severity of community-reported odors.
* Develop statistical models (OLS, Poisson GLM, Piecewise Linear, and Logistic Regression) to predict the **Odor Risk Index (ORI)**—the probability of a community-wide odor trapping event.
* Implement a de-biased Meteorological Odor Risk Index that neutralizes temporal human reporting biases (like weekend drops and holiday dips) to isolate pure weather-driven risk.

---

## 📁 Repository Directory Structure

```
weather-varaible-analysis/
├── FUTURE_IDEAS.md                     # Living backlog of ideas, priorities, and questions
├── AI_HANDOFF.md                       # This file (AI-to-AI handoff & context sync)
├── DEPLOYMENT.md                       # GitHub Pages + university server deployment guide
├── CALVERT_FORECASTER_REVIEW.md        # Full methodology audit (Tier-1/2/3 findings)
├── odor_forecast_core.py               # NEW — pure model logic (no Streamlit); single source of truth
│                                       #   for COEFFS_PITTSBURGH, COEFFS_EST_CALVERT,
│                                       #   PRESSURE_ELEVATION_OFFSET, calculate_bearing,
│                                       #   check_wind_alignment, get_risk_meta, predict_ori,
│                                       #   fetch_forecasts, fetch_historical_weather
├── calvert_odor_forecaster.py          # Streamlit UI only; imports all logic from odor_forecast_core
├── generate_site.py                    # Headless cron entry point → writes docs/data/*.json
├── calvert_tester_logs.db              # SQLite database storing tester dispatches and reports
├── calvert_zips.geojson                # Filtered Kentucky ZIP code boundary coordinates
├── docs/                               # GitHub Pages publish root (served statically)
│   ├── index.html                      # Page shell (4 tabs: Map, 16-Day, 30-Day, Report)
│   ├── style.css                       # Card/badge/calendar styling
│   ├── model.js                        # Client-side ORI math — mirrors predict_ori exactly
│   ├── app.js                          # Data loading, controls, Leaflet map, calendar, report tab
│   ├── calvert_zips.geojson            # Copied here by generate_site.py at generation time
│   └── data/                           # GITIGNORED — regenerated daily by generate_site.py / CI
│       ├── forecast.json               # 16-day raw weather features per ZIP per day
│       ├── historical.json             # 30-day raw weather features per ZIP per day
│       └── meta.json                   # Coefficients, pressure_offset, slider ranges, timestamp
├── .github/workflows/forecast.yml      # Daily cron 06:00 UTC → generate_site.py → Pages deploy
├── Odor_Complaint_Analysis_Walkthrough.md
├── Odor_Complaint_Analysis_Walkthrough.html
├── compile_report.py
├── public_dashboard_mockup.py
├── generate_metadata.py
├── Pittsburgh Data/                    # Pittsburgh, PA specific assets
│   ├── open-meteo-smell-merged.csv
│   ├── Odor_Complaint_Analysis_v2.ipynb
│   ├── Odor_Complaint_Analysis_v2.py
│   ├── Odor_Complaint_Analysis_v2_debiased.ipynb
│   ├── Odor_Complaint_Analysis_v2_debiased.py
│   ├── fetch_weather_for_zips_pittsburgh.py
│   ├── merge_smell_weather_pittsburgh.py
│   ├── pittsburgh_zips.geojson
│   └── laor_public_dashboard.png
├── Louisville Data/                    # Louisville, KY specific assets
│   ├── open-meteo-smell-merged.csv
│   ├── Odor_Complaint_Analysis_v2.py
│   ├── Odor_Complaint_Analysis_v2_debiased.py
│   ├── Odor_Complaint_Analysis_v2_stats.py
│   ├── Odor_Complaint_Analysis_v2_stats_debiased.py
│   ├── fetch_weather_for_zips.py
│   ├── merge_smell_weather.py
│   └── merge_clean_data.py
├── wyoming_soundings/
└── scratch/                            # Tests (gitignored dir, force-added individually)
    ├── test_forecast_engine.py         # 5 tests for odor_forecast_core (all pass)
    ├── test_generate_site.py           # 2 schema tests for generate_site.py (all pass)
    └── test_js_model.py                # JS/Python ORI parity test (skipped if node absent)
```

---

## 📊 Core Dataset & Variables
The daily merged meteorological datasets (`open-meteo-smell-merged.csv`) contain:
* `complaints`: Daily count of odor reports in the target city.
* `temperature`: Daily mean ambient air temperature (°F).
* `temp_min` / `temp_max`: Minimum and maximum daily temperatures (°F).
* `diurnal_temperature_range (DTR)`: Daily maximum minus minimum temperature ($DTR = \text{temp\_max} - \text{temp\_min}$). Strong proxy for nighttime radiative cooling and temperature inversion strength.
* `precipitation`: Daily sum of rainfall (inches).
* `wind_speed`: Daily mean wind speed (mph).
* `wind_direction`: Daily mean wind direction (degrees, 0–360°).
* `dew_point`: Daily mean dew point temperature (°F).
* `relative_humidity`: Daily mean relative humidity (%).
* `vapor_pressure`: Daily mean vapor pressure deficit (kPa).
* `atmospheric_pressure`: Daily mean surface pressure (hPa).
* `sunshine_duration`: Daily sum of sunshine exposure (seconds).
* `solar_radiation`: Daily mean shortwave solar radiation ($W/m^2$).
* `boundary_layer_height (BLH)`: Daily mean planetary boundary layer height (feet) — captures vertical mixing depth.
* `smell_value_average`: Daily average reported smell severity (1–5 scale, where 1 = barely noticeable, 5 = extreme).
* `is_weekend`: Binary flag (1 = Saturday/Sunday, 0 = Weekday).
* `is_holiday`: US federal holiday indicator (using the `holidays` Python package).

---

## 🔬 Key Methodologies & Statistical Findings

### 1. Spatiotemporal & Behavioral Characteristics
* **The Diurnal Cycle:** Complaints exhibit sharp peaks at **8:00 AM** and **6:00 PM – 8:00 PM**, reflecting human waking/returning-home routines combined with diurnal atmospheric boundary layer transitions (inversion break-ups and formation).
* **The Weekend Drop:** Average daily complaint frequency drops significantly on weekends (**-16.7% in Pittsburgh**: 36.8 to 30.7 complaints/day). This reflects behavioral variations (people staying inside/leaving town) and potential weekend reductions in industrial emissions.

### 2. Meteorological Correlations
* **Vertical and Horizontal Mixing:** Daily Spearman rank correlations ($rho$) show that **Boundary Layer Height ($-0.404$)** and **Wind Speed ($-0.334$)** are strongly negatively correlated with complaints. Poor ventilation (low BLH and calm winds) is the dominant physical driver of high odor complaint days.
* **Clairton Coke Works Wind Rose:** Localized wind rose analysis for top-reporting ZIP codes (15217, 15218) shows a distinct clustering of complaints when wind blows from the **South-Southeast (SSE)**, pinpointing the Clairton Coke Works facility located southeast of Pittsburgh.

### 3. Piecewise Temperature Regression
* **Threshold Split at 50°F:**
  - **Cool Days ($\le$ 50°F):** Strong positive correlation between temperature and complaints ($r = 0.215$, $p < 0.001$). As the temperature rises, chemical volatility increases, and more people go outdoors, increasing reports.
  - **Hot Days (> 50°F):** Flat/negative correlation ($r = -0.124$, $p < 0.001$). On hot days, residents stay indoors with windows closed and air conditioning running, which reduces exposure and dampens reporting.

### 4. Count Models: Poisson vs. OLS
* A **Poisson GLM** with log-link ($\ln(\lambda) = X\beta$) is used to model count data correctly, guaranteeing non-negative predictions.
* **DTR (Diurnal Temperature Range)** is a highly significant positive predictor (Poisson coef = 0.074, $p < 0.001$), confirming that strong nighttime radiative cooling (large temperature swings) correlates with morning inversion trapping.

### 5. Logistic Regression & Odor Risk Index (ORI)
* **Weighted Odor Burden** = Daily Complaint Count $\times$ Daily Average Smell Severity (1–5 scale).
* **Odor Event (1 / 0):** Defined as days exceeding the citywide mean weighted odor burden (**129.3 in Pittsburgh**).
* **Odor Risk Index (ORI):** Predicted probability (0–100%) of an odor event.
  - An increase in DTR of 1°F increases the odds of an odor event by **26.1%** (OR = 1.261).
  - A decrease in BLH of 100 feet increases the odds of an event by **4%** (OR = 1.0004 for height in feet).
  - Holding weather constant, weekends have **26.8% lower odds** of an event (OR = 0.732, $p = 0.006$), confirming weekend emission reductions or behavior shifts.

### 6. Meteorological Odor Risk Index (Normalized De-biasing)
* **The Problem:** Including temporal dummies (e.g. `dow_sun`, `is_holiday`) causes the model to predict low risk on a stagnant Sunday simply because people report less on Sundays.
* **The Solution:** The de-biased models train with temporal variables but **neutralize** them during predictions (all day-of-week dummies and `is_holiday` are set to `0.0`). This defaults the prediction to a Monday non-holiday baseline, representing pure meteorological trapping risk assuming 24/7 continuous industrial emissions.
* De-biased models show higher out-of-sample sensitivity (Recall increases from 57.98% to 59.70% in Pittsburgh).

### 7. Event Threshold Sensitivity Analysis
* Sensitivity analysis on daily complaint counts for both Pittsburgh and Louisville evaluated how varying the threshold (defining an "odor event" day) impacts Pseudo $R^2$ and out-of-sample 5-fold CV ROC-AUC.
* **Pittsburgh:** Peak performance is reached at a threshold of **30–50 daily complaints** (ROC-AUC = 0.864 to 0.874, Pseudo $R^2 \approx 0.32$), validating the severity-weighted mean threshold (which averages $\approx 32$ complaints/day).
* **Louisville:** Low thresholds (e.g. 1 complaint/day) have very poor correlation with weather (ROC-AUC = 0.645). Increasing the threshold to **10–15 complaints/day** filters out baseline noise and boosts out-of-sample ROC-AUC to **0.807–0.850** and increases Pseudo $R^2$ five-fold.

### 8. Precipitation Outlier Artifact (Data Alignment)
* Daily binned plots showed an apparent outlier where complaint rates remained high on days with high precipitation.
* **Hourly Audit:** Investigating specific outlier dates (e.g., Feb 24, 2020 and Mar 25, 2021) revealed this is a **temporal aggregation artifact**. The complaints peaked sharply in the dry morning hours (6:00 AM – 11:00 AM) whereas the rain fell much later in the afternoon/evening. This was documented in the notebooks via Markdown notes.

### 9. Calvert City Odor Event Forecasting System — Methodology Corrections (2026-06-23)
Four methodology fixes were applied to `calvert_odor_forecaster.py` (see full audit in `CALVERT_FORECASTER_REVIEW.md`):
* **Pressure elevation offset** (`PRESSURE_ELEVATION_OFFSET = 17.4 hPa`): Pittsburgh training mean surface pressure is 980.9 hPa (elevation ~370 m); Calvert City is ~998.3 hPa (~115 m). Subtracting the offset in `predict_ori` corrects a systematic ~5–8 ORI-point understatement and puts synoptic anomaly signals in the correct training frame.
* **Circular wind-direction mean**: Daily wind direction is now computed as a speed-weighted vector mean (u/v Cartesian components) instead of an arithmetic mean of degrees. The arithmetic mean fails at the 0°/360° wrap — e.g., 350° and 10° arithmetic-average to 180° (opposite direction), corrupting the wind-corridor transport filter.
* **Historical calendar recency**: Switched from ERA5 Archive API (5-day lag → blank recent calendar cells) to the forecast endpoint with `past_days=31` (no lag). Most recent calendar days now always populate.
* **Wind multiplier calibration**: Penalty/boost now applied in log-odds space (`z += log(multiplier)`) before the sigmoid, so ORI output stays a properly calibrated logistic probability. Added math.exp overflow guard.

### 10. Original Calvert City Odor Event Forecasting System
* A dynamic forecasting dashboard ([calvert_odor_forecaster.py](file:///Users/nawrig04/weather-varaible-analysis/calvert_odor_forecaster.py)) was developed to predict odor trap risks in Calvert City using weather forecasts and the Pittsburgh logit model.
* **Three Operational Modes:** Enables switching between *Exact Pittsburgh* coefficients, *Estimated Calvert City* coefficients (increased sensitivity to wind speed and boundary layer height drops to account for rural terrain), and *Custom Coefficients* (adjustable via sliders).
* **Wind Direction Filtering & Boosting:** Evaluates if incoming wind direction aligns with the opposite of the source-to-receiver bearing (direct transport corridor). If winds blow away from a ZIP code, risk is scaled down by a `wind_penalty_pct` slider (default `75%`, representing a `0.25` multiplier). If they align directly, risk can be scaled up by a `wind_boost` slider (default `1.0`, adjustable to `3.0`) to model localized close-proximity advection.
* **Translucent ZIP Boundaries:** Renders translucent, color-coded ZIP code polygon boundaries (`calvert_zips.geojson`) using a Pydeck `GeoJsonLayer` over CartoDB's public Positron GL base tiles. Hovering over a polygon shows localized risk details and ZIP code labels.
* **Extended 16-Day Forecast Outlook Grid:** Extended the future forecast calendar from 7 days to 16 days (the Open-Meteo API limit) and refactored the interface to render a clean 2x8 column grid to fit all 16 days of predictions without visual clutter.
* **Rolling 30-Day Historical Monthly Calendar View:** Replaced the Meteorological Trends tab with an interactive monthly calendar. It queries the Open-Meteo Archive API (`https://archive-api.open-meteo.com/v1/archive`) to calculate historical daily risk (using active coefficients and wind filters) and displays it in a clean Monday-Sunday aligned grid with click-to-expand details popovers.
* **Paid Tester Management Panel & UX Enhancements:** Reworked the panel to support both scheduled and ad-hoc (unscheduled) reports. Removed the `st.form` wrapper to ensure instant conditional rendering of the severity slider when "Odor Detected" is toggled, preventing duplicate submissions. Added dynamic operational metrics summary cards, a **Cancel Dispatch** utility to remove scheduled dispatches, **inline report deletion buttons (🗑️)** directly on each feedback report row (which automatically cleans up orphaned ad-hoc dispatches and reverts pre-scheduled dispatches back to 'Scheduled'), and placed database logs clearing actions in a secure safety expander.
* **Geolocation, Autofill, Smell My City Schema, and Protected Admin Panel:** Implemented a series of advanced features in the Paid Tester Management Panel:
  * **Client-side Geolocation**: Implemented browser geolocation retrieval (`navigator.geolocation.getCurrentPosition`) sandboxed in an iframe component, returning data back to the app via URL parameters or alerting coordinates as a backup.
  * **Privacy-Preserving Skew Mode**: Added a privacy button that skews coordinates with a small random offset (+/- 0.002 degrees) to prevent exact home coordinates from being stored.
  * **Smell My City Schema Alignment**: Expanded the reports database schema to include `latitude`, `longitude`, `odor_description`, and `symptoms`, providing multiselect filters for standard odor descriptions and symptoms. If "Other" is selected in the symptoms list, a dynamic free-text input is rendered to let users log custom symptoms which are appended to the report. Custom details for odor descriptions are captured in the general comments box.
  * **Tester Name Autofill**: Saves and loads the tester's name automatically using a local `.tester_config.json` cache file.
  * **Credentials Protection**: Restricted administrative operations (viewing reports list, CSV downloads, dispatches registry, and clears) behind a credential prompt (`admin` / `calvert2026`).
* **Global Theme-Adaptive HTML/CSS Styling:** Replaced all hardcoded CSS colors/borders in layout custom components (forecast cards, calendar grids, sidebars) with CSS theme variables like `var(--text-color)`, `var(--secondary-background-color)`, and `var(--border-color)`. This guarantees full dark-mode compatibility and solves accessibility contrast issues.

---

## 🔄 Collaboration & Hand-off Protocol

To ensure seamless coordination between Gemini and Claude Code, follow this protocol:

1. **Check Status Before Coding:**
   - Read this file `AI_HANDOFF.md` first to understand the current state.
   - Read `FUTURE_IDEAS.md` to see what is currently in progress, what is in the backlog, and what research questions are open.
2. **Log Progress During Execution:**
   - If writing code or making major edits, update `FUTURE_IDEAS.md` (e.g., move items from Backlog to In Progress, or to Completed).
3. **End-of-Session Sync:**
   - Before completing your run, update `AI_HANDOFF.md` with:
     - Any new scripts or files created.
     - New statistical models or parameters established.
     - Key findings or anomalies uncovered.
   - Commit changes so they are synced in the repository.

### 11. Static GitHub Pages Forecast Site (2026-06-23, branch: static-forecast-site → merged main)

A fully static daily-regenerated forecast website was built and deployed to GitHub Pages.

**Architecture (Option B — Python data generator + static HTML/JS shell):**
- `odor_forecast_core.py` — pure model logic extracted from the Streamlit app (no Streamlit imports). Single source of truth for all coefficients, `PRESSURE_ELEVATION_OFFSET`, and the four methodology-corrected functions.
- `calvert_odor_forecaster.py` — refactored to import from core; only Streamlit UI code remains. `fetch_forecasts` and `fetch_historical_weather` are wrapped with `@st.cache_data` at import time.
- `generate_site.py` — headless cron entry point. Calls `core.fetch_forecasts` + `core.fetch_historical_weather`, emits **raw model features** (not ORI) into `docs/data/forecast.json`, `docs/data/historical.json`, and `docs/data/meta.json` (which carries exported coefficients). ORI is computed entirely client-side in the browser.
- `docs/model.js` — pure JavaScript ORI math mirroring `predict_ori` exactly (`computeZ`, `computeOri`, `getRiskTier`). Dual-mode: browser global + Node `module.exports`.
- `docs/app.js` — loads JSON, wires live controls (mode, wind filter, penalty, boost), renders 4 tabs: Leaflet map with live polygon recolor, 16-day forecast card grid, 30-day historical calendar, report tab.
- `docs/index.html` — static shell with `window.GOOGLE_FORM` config block (real form ID and lat/lon entry IDs already populated).
- `.github/workflows/forecast.yml` — daily cron at 06:00 UTC (~1 AM Central); runs `generate_site.py` then deploys `docs/` to GitHub Pages via `actions/deploy-pages@v4`.

**Google Form integration:**
- Form URL: `https://docs.google.com/forms/d/e/1FAIpQLScJhcqfA3ZsgGOUcYdRXBw0aPOZb3_t1WnlcU9Lx6P2FJgHtQ/viewform`
- Latitude entry: `entry.1224216756`, Longitude entry: `entry.1314282346`
- Report tab has two one-click buttons: "📍 Use My Exact Location" and "🛡️ Use Approximate Location (Privacy)". Each button grabs `navigator.geolocation`, appends lat/lon as pre-fill query params, and immediately opens the form in a new tab — no separate "Open Form" button.

**JSON cell keys** (used in both Python generator and JS): `aligned, wind_alignment, distance, temp, temp_sq, solar, rh, wind_speed, wind_dir, precip, dtr, blh, pressure`
- `wind_alignment` is the new **continuous cosine alignment factor (0–1)** replacing the binary `aligned` for the continuous-mode wind filter.
- Locations are now **census tracts** (GEOID as key) instead of ZIP codes.

**Map Layers scaffold:** Risk layer active; Plume and Reports layer checkboxes present but disabled (pending `docs/data/plume.json` and `docs/data/reports.json` — see FUTURE_IDEAS backlog item `1-PLUME`).

**Deployment status (2026-06-23):** Main branch successfully pushed to GitHub Pages and local Gitea remotes. The GitHub Actions workflow automatically regenerates and deploys the static site to GitHub Pages on every push.

**To preview locally:**
```bash
.venv/bin/python generate_site.py
.venv/bin/python -m http.server 8765 --directory docs
# open http://localhost:8765/
```

**Test suite (all passing):**
```bash
.venv/bin/pytest scratch/test_forecast_engine.py scratch/test_generate_site.py scratch/test_js_model.py -v
# 8 passed, 1 skipped (JS parity skipped — node not installed locally; runs in CI)
```

### 12. Spatial Proximity & Multi-Source Regression Handoff (Added 2026-06-23)
* **Calvert City Distance Decay**: Implemented a distance-decay adjustment ($z_{\text{new}} = z_{\text{old}} - \text{decay\_rate} \times \text{distance}$) using the Haversine formula in miles from the Calvert City Industrial Complex center. Exposed this as a toggleable checkbox and a slider (defaulting to a calibrated **`0.02` per mile** rate) in both the Streamlit app sidebar and the static web page. Reorganized the static web page sidebar to group the Wind Corridor Filter and Distance Decay under a "Spatial & Dispersion" heading inside distinct, styled control-group panels for a cleaner, unified layout.
* **Multi-Source Regressions (`scratch/analyze_multi_source.py`)**: Conducted daily ZIP-date panel regressions (over 100,000 observations per city) for Pittsburgh and Louisville to evaluate proximity to multiple emitters simultaneously (including Rubbertown and Butchertown's JBS Swift plant for Louisville, and three Mon Valley steel/coke plants for Pittsburgh).
  * *Louisville*: Incorporating both sources under the exponential decay model with $k=0.03$ or $k=0.02$ more than triples the model's explained variance (base $R^2 = 0.0103$ vs. **$0.0349$ for $k=0.03$** and **$0.0339$ for $k=0.02$**) and drops the AIC score by **2,631** ($k=0.03$) and **2,527** ($k=0.02$) points.
  * *Pittsburgh*: Including Edgar Thomson and Irvin Works alongside Clairton Coke Works increases $R^2$ from base $0.0596$ to **$0.0832$ for $k=0.03$** and **$0.0830$ for $k=0.02$** (dropping AIC by **2,615** and **2,585** points, respectively).
  * *Decay Rate Justification*: While the urban models have a marginally higher fit with $k=0.03$ due to greater physical obstructions and mechanical turbulence in cities, a rate of **`0.02`** is selected as the Calvert City default. Calvert City's open, rural terrain has fewer mechanical obstacles (e.g. high-rises, dense hills) to block or disperse smell plumes, physically allowing odors to carry farther, which is modeled by a lower decay rate.
* **Jupyter Notebook Integration**: Created and executed `scratch/append_spatial_analysis.py` (and updated via `scratch/update_spatial_analysis_to_002.py`) to append this new panel regression analysis block ("Section 5: Spatial Proximity & Multi-Source Distance Decay Analysis") comparing $k=0.03$ and $k=0.02$ to the end of all four Jupyter notebooks (`.ipynb` files) and their Python script equivalents (`.py` files) in `Pittsburgh Data/` and `Louisville Data/`.
* **Sync Status**: Staged, committed, and pushed all updates to Gitea (`origin main`) and GitHub (`github main`).

### 13. Proximity Features, Dual-Model Notebooks, Census Tracts & Frontend Overhaul (2026-06-24)

#### Dual-Model Analysis Notebooks (Pittsburgh & Louisville)
* **New files:** `Pittsburgh Data/Dual_Model_Proximity_Analysis.py` + `.ipynb`, `Louisville Data/Dual_Model_Proximity_Analysis.py` + `.ipynb`
* **New feature: Continuous Wind Alignment Factor (0–1)** — cosine-based, replaces discrete 8-sector bins. Formula: `(1 + cos(wind_toward − bearing)) / 2` where `wind_toward = (wind_from + 180°) % 360`.
* **New feature: Multi-Source Exposure** — `sum(exp(-0.02 * dist_src))` across all emitters (Rubbertown + JBS Swift for Louisville; Clairton + Edgar Thomson + Irvin Works for Pittsburgh).
* **Screening results — both features p < 0.0001:**
  * Pittsburgh: ΔAIC = −889, ΔPseudo-R² = +0.022, CV AUC 0.906 → 0.910
  * Louisville: ΔAIC = −5,376, ΔPseudo-R² = +0.128, CV AUC 0.674 → 0.829
* **Exported coefficients:** `Pittsburgh Data/model_coeffs_pittsburgh.json`, `Louisville Data/model_coeffs_louisville.json`

#### New Prediction Mode: Pittsburgh Proximity-Enhanced
* **`COEFFS_PITTSBURGH_PROXIMITY`** added to `odor_forecast_core.py` — trained Pittsburgh zip-day panel logit including `multi_source_exposure` and `wind_align_weighted` regression terms.
* Exposed as `"pittsburgh_proximity"` mode in `generate_site.py` → `meta.json` → mode selector dropdown.
* `predict_ori()` now applies proximity coefficients automatically when present in the coeff dict.
* **Calibration note:** The `precipitation` coef is +6.66 (positive, vs −0.864 in city-level model) due to different aggregation level (zip-day panel vs. city-wide daily). This mode is experimental; compare against the existing modes.

#### Calvert City Spatial Resolution: ZIP → Census Tracts
* **New script:** `scratch/fetch_census_tracts.py` — downloads 2020 TIGER tracts for Marshall (10), McCracken (19), Livingston (3) counties via TIGERweb REST API (layer 6).
* **New file:** `calvert_tracts.geojson` (repo root) — 32 census tract polygons with `GEOID` property.
* `LOCATIONS` in `odor_forecast_core.py` replaced: 7 ZIP codes → 32 census tracts (key format: `"TRACT {GEOID} (…)"`).
* `docs/calvert_areas.geojson` — the tracts file deployed to docs/ for Leaflet. Replaces `calvert_zips.geojson`.

#### Continuous Wind Alignment in Core & Site
* `compute_continuous_wind_alignment(wind_from_deg, bearing_deg)` added to `odor_forecast_core.py`.
* Both fetch functions compute `wind_alignment` float column per row.
* `predict_ori()` has `use_continuous_alignment` param; when True, interpolates log-odds multiplier between `wind_penalty` and `wind_boost` using alignment (0–1).
* `generate_site.py` emits `wind_alignment` float in every JSON cell.
* `docs/model.js` `computeOri()` branches on `opts.continuousAlignment` — continuous or discrete.

#### Frontend Changes (docs/)
* **`docs/index.html`**: Added `tsEntry: ""` to GOOGLE_FORM config (set to your form's timestamp entry ID), "Continuous Alignment" checkbox in Wind Corridor Filter group.
* **`docs/app.js`**: `opts()` includes `continuousAlignment`; `renderMap()` uses GEOID key from `f.properties.GEOID`; "📍 Use My Location" button centers map + shows nearest tract ORI; `buildFormUrl()` injects ISO timestamp when `tsEntry` set; loads `calvert_areas.geojson`.
* **`docs/style.css`**: Mobile-responsive `@media (max-width: 700px)` — sidebar stacks vertically, tabs scroll horizontally, map 320px, 2-col card grid; `.btn-locate` button style.

#### Test Suite
* `scratch/test_forecast_engine.py` — added `test_continuous_wind_alignment` (perfect/no/crosswind cases).
* `scratch/test_generate_site.py` — updated assertions for GEOID-keyed locations, `wind_alignment` float in cell, and new `pittsburgh_proximity` mode in meta.
* **All 9 tests pass** (1 skipped — JS parity, Node absent locally; runs in CI).

### 14. Model Calibration Fixes, UI Overhaul & Calvert Data Pipeline (2026-06-24 → 2026-06-25)

#### Default Mode & Sidebar Cleanup
* **`pittsburgh_proximity`** set as default mode (previously had been switched to `calvert_proximity` then reverted after calibration issue — see below).
* **Spatial & Dispersion controls** (wind filter, continuous alignment, distance decay checkboxes) removed from the sidebar entirely. Those settings are now only active in Custom mode via the Spatial Adjustments sliders (`penalty_pct`, `boost`, `decay_rate`). For all preset modes, `windFilter=false` and `distanceDecay=false` — the proximity regression terms handle spatial adjustment natively.
* **Custom coefficient panel** now has two sections: "Model Coefficients" (10 weather terms + `multi_source_exposure` + `wind_align_weighted`) and "Spatial Adjustments" (`penalty_pct`, `boost`, `decay_rate`).

#### Calvert City Proximity Model — Calibration Issue & Fix
* **`COEFFS_CALVERT_PROXIMITY` (created then removed from dashboard):** Attempted to combine `COEFFS_EST_CALVERT` weather terms (const=+18.0, calibrated WITHOUT proximity terms) with Pittsburgh's proximity regression terms (+2.07 z-contribution on average). This produced ORI=96.5% for a typical nice summer day (z=+3.32). The const in `COEFFS_EST_CALVERT` was calibrated assuming no proximity contribution; adding ~+2.07 z-units broke the intercept.
* **Resolution:** Removed `calvert_proximity` from the dashboard dropdown. `COEFFS_CALVERT_PROXIMITY` is preserved in `odor_forecast_core.py` for reference only (not exposed). Default reverted to `pittsburgh_proximity`.
* **Key lesson:** Never mix a regression intercept from model A with predictor coefficients from model B. The const is jointly estimated with all other terms and is not portable in isolation.

#### Precipitation Coefficient Fix in `pittsburgh_proximity`
* The raw zip-day panel fit produced `precipitation = +6.66` (positive — each inch of rain → ~780× odds). On heavy-rain days (3–4 inches) this term alone hit z=+20 to +26, saturating ORI to 100%.
* **Root cause — zip-day panel overfitting:** The panel repeats city-wide weather for every ZIP on the same day. If rainy days coincided with complaint spikes for unrelated reasons, the amplified panel structure assigned the spike to precipitation. The city-wide daily model (one row per city-day) produced −0.864 (physically correct — rain scavenges odor).
* **Fix:** Override `precipitation` in `COEFFS_PITTSBURGH_PROXIMITY` with −0.864070 (city-wide validated value). Safe because precip=0 on most days, so dry-day calibration (the jointly-fit intercept) is completely unchanged; only rainy-day behavior is corrected. Raw value preserved as `_PROX_PRECIP_RAW = 6.65637`.
* **Result on Tract 401 (Livingston Co.), 32-day window:** before: 5 days at ~100%, 8 High, mean 36.3% → after: 0 at 100%, 0 High, mean 14.2%, max 45.5%.

#### Debiasing Confirmed
* Both `pittsburgh_proximity` and all other deployed modes are fully debiased: `dow_*` and `is_holiday` dummies are included during training (to control for reporting behavior) but stripped from the deployed coefficient dict. Confirmed by auditing `model_coeffs_pittsburgh.json` (has all 7 dummies) vs `COEFFS_PITTSBURGH_PROXIMITY` in `odor_forecast_core.py` (zero temporal dummies). Largest dummy effect was ~0.22 log-odds (modest).

#### Mini-Maps on 16-Day & 30-Day Tabs
* **`docs/app.js`** — replaced the `<select>` dropdowns on the 16-Day and 30-Day tabs with lazy-initialized Leaflet mini-maps (200px height). Mini-maps:
  - Color census tracts by today's ORI (same color scheme as the main map tab).
  - Allow click-to-select a tract; label updates to tract name.
  - "My Location" geolocation button auto-selects the nearest census tract.
  - Share `APP._mapState.geojson` with the main map tab via `ensureGeoJson()`.
  - State tracked in `APP._locMaps` closures keyed by `"forecast"` / `"monthly"`.
  - Lazy initialization via `buildLocSelectMap(tabKey)` — called only when the tab is first activated.

#### Coefficient Audit Tool (full spread analysis)
* Ran a complete term-by-term audit of `COEFFS_PITTSBURGH_PROXIMITY` against live data, measuring each term's actual z-contribution spread across all cells. Key finding: only precipitation was pathological (spread 48 log-odds units, wrong sign). All other coefficients had spreads of 0.15–6.3 and were physically defensible. Diurnal temperature range (spread 5.94) is the largest legitimate driver — physically correct (nocturnal inversion trapping).

#### Calvert City Report → Coefficient Analyzer (`analyze_calvert_reports.py`)
* **New script** at repo root. Run periodically once real Calvert odor reports accumulate to test whether any deployed coefficient (weather, wind_alignment, distance decay, precip) should be adjusted for Calvert's chemical-plant sources vs Pittsburgh's coke/steel works.
* **Two data sources:** SQLite tester db (`calvert_tester_logs.db`, `reports` table with `odor_detected` yes/no) and/or Google-Form responses CSV / published-sheet URL (presence-only with severity 1–5).
* **Two statistical modes auto-detected:**
  - CASE-CONTROL: when `odor_detected` yes/no is present (tester db) → direct logistic regression.
  - USE-vs-AVAILABILITY: presence-only (public form) → report days as "used", background climatology as "available" controls. Logit coefficients come out on the same scale as the deployed model for direct comparison.
* **Severity weighting:** Public form's 1–5 severity now used as sample weights in the fit (stronger smells count more). NOT presence-only in the everyday sense (rich form with severity/symptoms/descriptions), but no recorded-absence rows, so use-vs-availability design is retained.
* **Weather fetch:** ERA5 archive via Open-Meteo for each report's coordinates + one prior day (for lag features). Results cached in `scratch/calvert_weather_cache.json`.
* **Features tested:** All 9 weather terms + `multi_source_exposure` + `wind_alignment` + `precipitation_lag1` (the residents' "after rain" hypothesis). Univariate screen + multivariate logistic regression vs deployed coefficients, flagging sign flips and magnitude divergences with p-values.
* **Model generation & install flow:**
  1. 5-fold cross-validated AUC for a locally-fit severity-weighted model vs deployed `pittsburgh_proximity`.
  2. Quality gates: `--install-min-reports` (default 50), `--auc-floor` (default 0.60), `--auc-margin` (default 0.02 beats deployed).
  3. If all gates pass → interactive terminal prompt "Add this model to the forecaster? [y/N]". `--yes` / `--no` flags for non-interactive use.
  4. On accept → writes `calvert_fitted_model.json` (only file the script ever modifies outside `scratch/`).
* **Forecaster integration (zero source edits per fit):**
  - `odor_forecast_core.py` auto-loads `calvert_fitted_model.json` at import → `COEFFS_CALVERT_FITTED` + `CALVERT_FITTED_META`.
  - `generate_site.build_meta()` exposes it as `"calvert_fitted"` mode labeled `"Calvert City (Data-Fitted) — N reports"` and makes it the default when present.
  - The three built-in models always remain available in the dropdown; the fitted model is additive.
  - To remove: delete `calvert_fitted_model.json` + re-run `generate_site.py` → default reverts to `pittsburgh_proximity`.
* **Usage:**
  ```bash
  .venv/bin/python analyze_calvert_reports.py                          # tester db only
  .venv/bin/python analyze_calvert_reports.py --csv responses.csv      # + form CSV
  .venv/bin/python analyze_calvert_reports.py --sheet-url "https://..." # + published sheet
  .venv/bin/python analyze_calvert_reports.py --yes                    # auto-install if gates pass
  ```

#### Methodology Tab (new 5th tab)
* **`docs/index.html`** — added `📖 Methodology` tab button + `#tab-methods` panel.
* **`docs/app.js`** — `renderMethodsTab()` (lazy-built, `dataset.built` guard) wired into `APP._onTab`. Explains: what ORI is + risk tiers, the shared physical drivers (DTR/BLH/wind = inversion physics), the two corrections (pressure offset + de-biasing), and a per-model card for every mode in `meta.mode_labels`.
* **`MODE_DOCS`** object in `app.js` holds the hand-written per-model prose (tagline, training data, how it works, notes, best-use), keyed by mode id. Modes present in meta but missing from MODE_DOCS fall back to a generic line, so future modes (e.g. `calvert_fitted`) render automatically — `calvert_fitted` has its own entry and surfaces `fitted_meta` (n_reports, CV AUC). Cards are data-driven from `meta.mode_labels`/`meta.default_mode`, so the page always matches the deployed models. Closes with a limitations section (Pittsburgh-borrowed, trapping-not-emissions, post-rain open question).
* **`docs/style.css`** — `.methods-wrap`, `.method-card`, `.model-card`, `.tier-row`, `.default-chip`, etc.

#### Open Scientific Question: Calvert Post-Rain Odor
* Calvert City residents reported strong odors **after rain**. Pittsburgh data shows the opposite (rain → fewer complaints, even lagged, Poisson p≈10⁻⁴²). Hypothesis: different source chemistry (chemical plants vs coke/steel) may genuinely produce different precipitation response.
* **Decision (Plan A+C):** Keep `precipitation = −0.864` (physically correct for our only real dataset); collect Calvert data with `analyze_calvert_reports.py` to settle empirically. The analyzer includes `precipitation_lag1` as an exploratory feature specifically to test the residents' claim.

#### Directory Structure Updates
```
├── analyze_calvert_reports.py   # NEW — periodic report→coefficient analyzer & model installer
├── calvert_fitted_model.json    # OPTIONAL (not committed) — written by analyzer on user accept
├── odor_forecast_core.py        # UPDATED — COEFFS_PITTSBURGH_PROXIMITY precip fixed (-0.864);
│                                #   COEFFS_CALVERT_FITTED auto-loader; CALVERT_FITTED_META
│                                #   _PROX_PRECIP_RAW preserved for reference
├── generate_site.py             # UPDATED — exposes calvert_fitted mode + meta when JSON present
└── docs/
    ├── app.js                   # UPDATED — mini-maps on 16-Day/30-Day tabs; My Location button;
    │                            #   APP._locMaps; buildLocSelectMap(); ensureGeoJson();
    │                            #   removed distance-decay/wind-filter toggle DOM refs
    └── index.html               # UPDATED — removed Spatial & Dispersion section; no toggle-row
```

### 15. Hourly Forecast Tab & Google Form Timezone Fix (2026-06-25)

**New feature: ⏱️ Hourly tab** — per-hour ORI forecast for all 16 forecast days and all 32 census tracts.

#### Data pipeline
- `odor_forecast_core.py`: added `fetch_hourly_forecasts(locations)` — same Open-Meteo hourly call as `fetch_forecasts` but returns one row per location × hour instead of aggregating. DTR (diurnal temperature range) is computed as daily max−min temperature and attached to all 24 hours of each day so the existing ORI logistic regression works unchanged. Mock fallback generates plausible sinusoidal diurnal patterns (temp, solar, BLH) for offline use.
- `generate_site.py`: added `build_hourly_payload(hourly_df)` → `docs/data/hourly.json` (384 datetime slots × 32 tracts, same cell schema as daily). Output is 2.8 MB uncompressed / **253 KB gzipped** (well within GitHub Pages limits). Lazy-loaded by the browser — does not delay initial page load.

#### Frontend
- `docs/index.html`: added `⏱️ Hourly` tab button and `#tab-hourly` panel section.
- `docs/app.js`:
  - Module-level `_hourlyLocId` / `_hourlyDate` state.
  - `buildHourlyTab()`: lazy-loads `hourly.json` on first tab open, builds a mini-map location picker (same pattern as 16-Day/30-Day tabs, colored by daily ORI from `APP.forecast`), a day `<select>` (16 options), and calls `renderHourly()`. Wires My Location button, day selector, and `APP.onChange` re-render.
  - `renderHourly()`: computes 24 hourly ORI values via `APP.oriFor(cell)` (cells carry `dtr` from the parent day), then renders:
    - **Inline SVG area/line chart** (600×180 viewBox, responsive via CSS `width:100%`): area fill + colored circles, tier threshold dashed lines at 15/30/50%, hour labels at 0/3/6/9/12/15/18/21, SVG `<title>` tooltips showing temp/wind/BLH/solar per hour.
    - **24-cell colored hour strip**: each cell background = ORI tier RGB, shows hour + ORI%, `title` tooltip with full inputs.
    - Risk tier legend.
  - `localTimestampStr()`: new helper that formats local time with UTC offset (e.g. `2026-06-25T09:30:00-05:00`).
  - `buildFormUrl()`: updated to use `localTimestampStr()` instead of `new Date().toISOString()` — timestamps now show the reporter's local time with timezone offset embedded. If `window.GOOGLE_FORM.tzEntry` is set, also pre-fills the IANA timezone name.
- `docs/style.css`: added `.hourly-chart`, `.hourly-chart-box`, `.hour-strip`, `.hour-cell`, `.hour-cell-label`, `.hour-cell-ori`, `.hourly-legend`. Mobile rule hides `.hour-cell-ori` to keep strip usable on narrow screens.

#### Google Form timezone field
`window.GOOGLE_FORM.tzEntry = null` added to `docs/index.html` — fill in the entry ID from the form's "Get pre-filled link" for the new Timezone short-answer field. Because the timestamp already includes the UTC offset, this field is optional but provides the IANA name (e.g. "America/Chicago") if desired.

#### Tests added
- `test_generate_site.py`: `test_build_hourly_payload_schema()` — validates 24×n_dates datetimes, all tract IDs present, required cell keys including `dtr`, correct types.
- `test_forecast_engine.py`: `test_hourly_dtr_attached_to_all_hours()` — uses `mock.patch` to force the mock fallback, then asserts every (loc_id, date) group has exactly one unique DTR and row count = 32 × 16 × 24.
- All 11 tests pass, 1 skipped (unchanged).

---

### 16. ERA5 BLH Backfill, Model Re-fit & Validation Charts (2026-06-25)

#### Problem fixed: synthetic BLH in H1-2024 training data
`Pittsburgh Data/open-meteo-complete_hourly.csv` was 100% null for `boundary_layer_height (ft)` across all 61 zip locations for exactly 2024-01-01 00:00 → 2024-06-30 23:00 (~266,448 rows, 5.9% of training data). The merge pipeline's 4-tier imputation was silently filling it with **month-hour median climatology** — smooth synthetic values with no day-to-day variability. This weakened the BLH signal in all three Pittsburgh-derived models.

#### Fix: Copernicus CDS ERA5 reanalysis
- `Pittsburgh Data/backfill_blh_era5.py`: fetches ERA5 `boundary_layer_height` from the Copernicus Climate Data Store for the H1-2024 gap, bounding box covering all 61 Pittsburgh zip centroids at 0.25° resolution. CDS credentials go in `~/.cdsapirc` (owner-read-only, **never in the repo**). ERA5 time is UTC and matches the raw CSV's UTC time column — direct join on `(location_id, time)`. Converts meters → feet. Downloads ~447 KB NetCDF, produces tidy `[location_id, time, blh_ft]` CSV (266,448 rows) in the session scratchpad.
- The raw hourly CSV is patched in-place (backup in scratchpad). **Verify**: 0 null BLH in window after patch; sanity sample shows realistic diurnal range (e.g. 303 ft overnight → 3,436 ft afternoon on 2024-03-15).

#### Model re-fit
- Re-ran `merge_smell_weather_pittsburgh.py` → rebuilt `open-meteo-smell-merged.csv` with real H1-2024 BLH.
- Re-ran `Odor_Complaint_Analysis_v2_debiased.py` → new `exact_pittsburgh` coefficients. AUC 0.8745 → 0.8694 (−0.5%, essentially unchanged). Pseudo-R² 0.387 → 0.337 (slightly lower — real BLH is noisier than synthetic medians, harder to fit but more honest).
- Re-ran `Dual_Model_Proximity_Analysis.py` → new `pittsburgh_proximity` coefficients + updated `model_coeffs_pittsburgh.json`. AUC 0.9099 → 0.9053.
- **Key coefficient changes**: BLH coefficient ~31% weaker in both models (expected — real variance vs smooth synthetic values). Precipitation stayed correctly negative. Wind speed strengthened (~60% in exact_pittsburgh).
- `odor_forecast_core.py`: updated `COEFFS_PITTSBURGH`, `COEFFS_PITTSBURGH_PROXIMITY`, `COEFFS_EST_CALVERT` (same manual deltas re-applied: const→18.0, wind_speed→−0.15, BLH→−0.0006). `_PROX_PRECIP_RAW` updated from 6.656 → 6.253; precipitation override updated to −0.908541 (new exact_pittsburgh value).

#### Model validation section (Methodology tab)
- `Dual_Model_Proximity_Analysis.py` Section 7: exports committed `model_metrics.json` (repo root) with 100-pt ROC + PR curve arrays, AUC, CV-AUC, pseudo-R², and optimal-F1 for all three models.
- `generate_site.py` `build_meta()`: reads `model_metrics.json` → `meta["model_metrics"]`; graceful no-op if absent (CI has no training data).
- `docs/app.js` `renderMethodsTab()`: new "Model Validation & Performance" section renders:
  - **Overlaid ROC SVG** (blue=Exact Pittsburgh, green=Proximity-Enhanced, amber=Est. Calvert City) + 45° chance diagonal.
  - **Overlaid PR SVG** with optimal-F1 dots.
  - **Metrics table**: AUC · CV-AUC · Pseudo-R² · evaluated-on.
  - Caption footnotes: exact_pittsburgh AUC is 0.76 on the zip-day panel (its native daily-panel AUC is 0.87); estimated_calvert is hand-tuned with no Calvert validation set.
- New **Weather Data Sources** card explains Open-Meteo (main) + Copernicus ERA5/CDS (BLH Jan–Jun 2024 gap).
- `docs/style.css`: `.validation-charts`, `.val-chart`, `.val-chart-svg`, `.val-legend*`, `.metrics-table` added.
- `scratch/test_generate_site.py`: `test_build_meta_model_metrics()` added — verifies curve arrays and AUC range; skips gracefully when `model_metrics.json` absent.
- `scratch/test_forecast_engine.py`: updated test inputs for `test_wind_direction_filter` and `test_distance_decay` to use higher solar/BLH inputs that produce moderate ORI (not saturated at 100%) with the new coefficients.
- **13/13 tests pass.**

#### LFS / git note
The two large Pittsburgh CSVs are git LFS tracked in Gitea (`origin`). Push to GitHub (`github` remote) with `GIT_LFS_SKIP_PUSH=1 git push github main` — GitHub only needs the code and committed artifacts (JSON, scripts, docs); the training CSVs are not needed for the forecaster.

#### Security
The CDS API key was used to fetch ERA5 data and stored **only** in `~/.cdsapirc`. It was never written to any tracked file or commit. The user should rotate it at [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu) after this session.

### 17. Scientific Audit & Hourly Tab Reframe (2026-06-25)

#### Audit conclusion
Full audit of daily vs hourly inference paths before mentor handoff.

**Daily path (Map / 16-Day / 30-Day): verified sound.** `fetch_forecasts` aggregates hourly weather into daily features using `precip:sum`, `solar:mean`, `temp:mean/min/max`, `rh:mean`, `pressure:mean`, `BLH:mean`, `DTR = max−min`, and circular vector-mean for wind direction — matching both training pipelines (`Odor_Complaint_Analysis_v2_debiased.py`, `Dual_Model_Proximity_Analysis.py`) exactly. No train/inference feature-parity violation on any daily tab.

**Hourly tab: the one real problem.** `fetch_hourly_forecasts` was emitting instantaneous hourly values, and the browser fed them into the daily-trained coefficients. Two clear violations:
- **Solar radiation**: instantaneous 0–620 W/m² vs the daily-mean range (~0–300 W/m²) the −0.016 coefficient was fit on → ~−10 log-odds at noon vs ~−3 in training. Artificially crushed midday risk.
- **Precipitation**: single hour's rain vs the daily total the −0.91 coefficient was fit on.
- **BLH / wind / RH**: all varying across a much wider range than their daily-mean training distributions.

#### Fix: hold daily-natured features constant per day

**`odor_forecast_core.py`**: New module-level helper `_apply_daily_aggregates_to_hourly(df, bearing, loc_name)` applies these overrides on each per-location hourly dataframe (both the live API branch and the synthetic mock fallback):
- `solar_radiation` → daily **mean**
- `precipitation` → daily **sum**
- `relative_humidity`, `atmospheric_pressure`, `wind_speed` → daily **mean**
- `wind_direction` → daily **circular vector-mean** (arctan2 on mean u/v components)
- `wind_alignment` / `aligned` → recomputed from the daily direction (constant across the day)
- **Left varying**: `temperature`, `boundary_layer_height` — the genuine sub-daily inversion drivers

Result: every feature the model sees is within its training distribution; only BLH and temperature shape the intra-day curve.

**`docs/app.js` `renderHourly`**:
- Heading changed to "Relative trapping conditions through the day" (aria-label updated to match).
- Y-axis values no longer show `%` (they're a relative index, not a probability).
- Tooltips now show "index X.Y" (not "X.Y%"), surface temp + BLH as the two varying drivers, and label wind as "(daily)".
- Strip cells show the index number without `%`.
- Legend tiers relabeled: "Favorable <15 / Moderate 15–30 / Elevated 30–50 / High ≥50" (no `%`).
- **Dashed daily-ORI anchor line** drawn across the SVG at the day's calibrated ORI from `APP.forecast`, labeled "Daily ORI X.X%".
- **Caveat box** below the chart explains: daily model, what's held constant, what varies, that the curve is a qualitative within-day indicator.

**`docs/app.js` `renderMethodsTab` limitations card**:
Added a fourth bullet explicitly describing the hourly tab's qualitative nature, the train/inference parity fix, and what's held vs. varied.

#### Tests
Extended `test_hourly_dtr_attached_to_all_hours` in `scratch/test_forecast_engine.py`:
- Asserts `solar_radiation`, `precipitation`, `relative_humidity`, `atmospheric_pressure`, `wind_speed`, `wind_direction` are all **constant** across all 24 hours of every (loc_id, date) group.
- Asserts `temperature` and `boundary_layer_height` **vary** within at least one group.
- All 13 tests pass.

#### Verified in generated data
`docs/data/hourly.json` confirmed: for 24 hours of a sample location/date, all 5 daily-natured features have exactly 1 unique value; temperature has 22 unique values; BLH has 23 unique values.

---
*Last updated: 2026-06-25 by Claude Sonnet 4.6 — Scientific audit, hourly tab reframe as qualitative relative indicator, 13 tests passing*

