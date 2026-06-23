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

**JSON cell keys** (used in both Python generator and JS): `aligned, temp, temp_sq, solar, rh, wind_speed, wind_dir, precip, dtr, blh, pressure`

**Map Layers scaffold:** Risk layer active; Plume and Reports layer checkboxes present but disabled (pending `docs/data/plume.json` and `docs/data/reports.json` — see FUTURE_IDEAS backlog item `1-PLUME`).

**Deployment status (2026-06-23):** Branch pushed to GitHub. Pages source set to GitHub Actions. Pending: PAT `workflow` scope must be enabled before `git push` can upload `.github/workflows/forecast.yml`. After push succeeds, manually trigger the workflow from Actions tab → "Daily Odor Forecast" → "Run workflow".

**To preview locally:**
```bash
.venv/bin/python generate_site.py
.venv/bin/python -m http.server 8765 --directory docs
# open http://localhost:8765/
```

**Test suite (all passing):**
```bash
.venv/bin/python -m pytest scratch/test_forecast_engine.py scratch/test_generate_site.py scratch/test_js_model.py -v
# 7 passed, 1 skipped (JS parity skipped — node not installed locally; runs in CI)
```

---
*Last updated: 2026-06-23 by Claude Sonnet 4.6 — static site build complete + deployment in progress*

