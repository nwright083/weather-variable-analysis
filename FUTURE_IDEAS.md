# Future Ideas & Enhancement Backlog
## Odor Complaint Weather Variable Analysis — Pittsburgh & Louisville

> **Purpose:** A living document to track future model enhancements, research ideas, and data acquisition tasks. Updated as new ideas emerge during analysis sessions.

---

## ✅ Completed Enhancements

### 1. Richer Temporal Controls (Option 1) — Completed 2026-06-17
**Scope:** Pittsburgh & Louisville `Odor_Complaint_Analysis_v2.py`  
**What was done:**
- Replaced binary `is_weekend` with 6 categorical day-of-week dummies (Monday = reference) + `is_holiday` flag in all regression models (OLS, Poisson, Severity, Logit/ORI)
- Added Section 3b exploratory plots: day-of-week profiles, monthly seasonality, seasonal grouped bars, holiday vs non-holiday comparison with Mann-Whitney test, point-biserial correlation table
- Installed `holidays` Python package for accurate US federal holiday detection
- Added `month`, `season`, and season dummy columns for exploratory analysis

---

### 2. Translucent ZIP-based Spatial Mapping & Wind Corridor Corrections — Completed 2026-06-23
**Scope:** Calvert City Odor Forecaster (`calvert_odor_forecaster.py`)
- Replaced point markers with colored, translucent ZIP code boundaries (`calvert_zips.geojson`) via Pydeck `GeoJsonLayer` to visualize regional risk.
- Fixed a 180-degree phase error in wind direction corridor transport logic (incoming wind must blow FROM the opposite of the source-to-receiver bearing).
- Parameterized the forecast cache key to prevent stale location mismatch issues.
- Added SQLite schema inspection and automatic database rebuilds on schema changes to prevent start crashes.
- Resolved Matplotlib polar rose ticks warnings and Streamlit container width deprecation logs.

---

### 3. Extended 16-Day Forecast Outlook & 30-Day Historical Calendar — Completed 2026-06-23
**Scope:** Calvert City Odor Forecaster (`calvert_odor_forecaster.py`)
- Removed the Meteorological Trends tab based on user preference to declutter the dashboard.
- Extended the future forecast window from 7 days to 16 days (the Open-Meteo API limit).
- Refactored the forecast outlook visual display into a clean 2x8 grid layout (8 columns) to fit the 16 days without cluttering.
- Implemented `fetch_historical_weather` pulling the past 30 days of weather data from the Open-Meteo Archive API.
- Integrated a rolling 30-day "Monthly Calendar View" tab aligned by weekday (Monday-Sunday) to view historical risk.
- Created styled HTML risk cards (Clear, Moderate, Elevated, High Risk) for each calendar day.
- Implemented clickable "Details" popovers (`st.popover`) displaying complete meteorological parameters (min/max temperature, wind speed/direction, boundary layer height, relative humidity, atmospheric pressure, rain) explaining the daily risk.
- Added a `wind_boost` slider to the sidebar (range 1.0 to 3.0, defaulting to a neutral 1.0) and integrated it into the calculations to boost risk predictions when wind directions blow directly towards a location, supporting localized close-proximity advection modeling.
- Refactored the `wind_penalty` slider into an intuitive percentage format (`0%` to `100%`) so that decreasing the penalty percentage correctly reduces the risk mitigation (thereby increasing the calculated risk), making user calibration intuitive.
- Added a descriptive `help` parameter to the sidebar Prediction Mode selectbox. Hovering over the question mark icon (`?`) in the sidebar renders a detailed markdown breakdown explaining the geographic and meteorological differences in sensitivity parameters between the urban Pittsburgh baseline and rural Calvert City.
- Custom-styled the sidebar "Parameters" heading, calendar cards, layout grids, and empty cells to dynamically inherit the Streamlit theme variables (`var(--text-color)`, `var(--secondary-background-color)`, `var(--border-color)`), resolving the readability/contrast issue where dark headings and borders clashed on dark-themed sidebars or backgrounds.
- Reworked the Paid Tester Management Panel: added dynamic KPI metric summary cards at the top, removed the rigid `st.form` container to make inputs instantly responsive and prevent duplicate submissions, implemented support for logging unscheduled ad-hoc reports (which registers a completed dispatch on the fly), conditionally hide/show the severity slider based on odor detection, added a **Cancel Dispatch** widget and **inline report deletion buttons (🗑️)** directly on report rows (with automatic database cleanup and dispatch reversion), and placed danger zone logs actions in a secure safety expander.

---

### 4. Browser Geolocation, Smell My City Schema, Autofill & Secure Admin Panel — Completed 2026-06-23
**Scope:** Calvert City Odor Forecaster (`calvert_odor_forecaster.py`)
- Added client-side browser geolocation retrieval with query parameter reloading and top-level redirection.
- Added a privacy-preserving "Get Skewed Location" button with random coordinate offset (+/- 0.002 degrees).
- Aligned database schema and form inputs with Smell My City fields (smell descriptions and symptoms multiselects) and added dynamic text inputs for custom symptoms when "Other" is chosen.
- Persisted and auto-filled tester name from `.tester_config.json`.
- Password-protected administrative metrics, logs list, delete operations, CSV downloads, database clears, and credentials updates via secure PBKDF2 hashing using fallback default credentials (`admin` / `calvert2026`).

---

### 5. Forecaster Methodology Corrections — Completed 2026-06-23
**Scope:** Calvert City Odor Forecaster (`calvert_odor_forecaster.py`)
- **Fix 1 — Pressure elevation offset:** Added `PRESSURE_ELEVATION_OFFSET = 17.4 hPa` constant to correct for the ~17 hPa elevation gap between Pittsburgh's training data (~370 m ASL, mean 980.9 hPa) and Calvert City (~115 m ASL, mean 998.3 hPa). Pressure term in `predict_ori` now uses `(pressure - offset)` so ORI reflects synoptic anomalies, not topographic artifacts. Raises mid-range ORI by ~5–8 pp.
- **Fix 2 — Circular wind-direction mean:** Replaced arithmetic mean of wind directions (invalid across 0°/360° wrap) with speed-weighted vector mean using u/v Cartesian components in both `fetch_forecasts` and `fetch_historical_weather`. Prevents the wind-corridor transport filter from misclassifying calm northerly flow as southerly.
- **Fix 3 — Historical calendar recency:** Switched `fetch_historical_weather` from the ERA5 Archive API (5-day lag → blank recent calendar cells) to the forecast endpoint with `past_days=31` (no lag). Most recent days now always populate.
- **Fix 4 — Wind multiplier calibration:** Moved the wind corridor penalty/boost from probability-space multiplication to log-odds-space addition (`z += log(penalty)`). ORI output is now a properly calibrated logistic probability. Added `math.exp` overflow guard.
- **Tier-2:** Removed unused matplotlib imports, fixed non-reproducible `hash()` seed in offline fallback (now uses `hashlib.md5`), corrected data source badge ("NOAA HRRR & GFS" → "Open-Meteo (NWP + ERA5)"), added sector-maintenance comment to `check_wind_alignment`.
- **Tests:** Updated `scratch/test_forecast_engine.py` — 2 tests corrected for new behavior, 2 new tests added (pressure offset, vector mean). All 5 pass.
- See full audit: `CALVERT_FORECASTER_REVIEW.md`.

---

## 🔧 In Progress

### Static Daily-Generated Forecast Website (GitHub Pages)
**Scope:** New `odor_forecast_core.py`, `generate_site.py`, `docs/` static site, GitHub Actions cron.
**Design doc:** `docs/superpowers/specs/2026-06-23-static-odor-forecast-site-design.md`
- Extract pure forecasting logic from `calvert_odor_forecaster.py` into `odor_forecast_core.py` (no Streamlit).
- `generate_site.py` fetches weather daily, writes raw model features + coefficients to `docs/data/*.json`.
- Static `index.html` + `app.js` (Leaflet map, vanilla-JS tabs) compute ORI client-side, with live controls
  for prediction mode (incl. Custom), wind filter, penalty %, and boost — mirroring the Streamlit sidebar.
- Report tab uses browser geolocation to pre-fill a Google Form (lat/lon as query params).
- GitHub Actions cron (`0 6 * * *`) regenerates JSON and deploys to GitHub Pages. Portable to a
  university/home server via plain crontab later.

---

## 📋 Backlog — Prioritized

### 1-PLUME. Plume Analysis & Odor Report Map Overlays (NEW)
**Priority:** High
**Effort:** High
**Description:** Once the static forecast site is live, add two additive Leaflet map layers (the Layers
control ships from day one with only the Risk layer active):
- **Plume / deposition layer** (`docs/data/plume.json`): daily-updated atmospheric plume dispersion and
  deposition footprint from the Calvert City industrial source — GeoJSON contours or a raster overlay
  showing where emissions are predicted to deposit each day, driven by the same wind/BLH inputs.
- **Odor reports layer** (`docs/data/reports.json`): severity-colored point markers for tester/community
  odor reports (exported from the Google Sheet, later a database). Lets us visually correlate where odors
  were *reported* against where the model predicts trapping and where the plume *deposited*.
**Why:** Combining forecast risk + modeled plume deposition + actual reports on one daily-updating map is
the core scientific payoff — visual validation of whether the meteorological model and plume physics
predict the locations where people actually smell odors.
**Approach:** Add `fetch_plume()` / `fetch_reports()` to `generate_site.py`'s data-sources section; render
as toggleable Leaflet layers in `app.js`. No change to the forecast pipeline (design is layer-first).
**Dependencies:** Static forecast site (In Progress) must land first; plume model source/format TBD.

### 1a. Louisville Model as Calvert City Prediction Mode (NEW)
**Priority:** High
**Effort:** Low–Medium
**Description:** Add a fourth "Louisville Model" option to the forecaster's Prediction Mode sidebar selector. The Louisville de-biased logit model (`Louisville Data/Odor_Complaint_Analysis_v2_debiased.py`) covers a flat-terrain chemical corridor more analogous to Calvert City than Pittsburgh's hilly urban basin. Requires: (a) running the Louisville de-biased logit to extract coefficients, (b) computing a Louisville pressure training mean for an elevation offset constant, (c) adding `COEFFS_LOUISVILLE` dict and the mode in the sidebar.
**Why:** Current "Estimated Calvert City" mode manually tweaks Pittsburgh coefficients with engineering judgment. Louisville provides an empirical calibration on a more geographically similar industrial area.

### 1b. Automatic Wind-Sector Derivation from GeoJSON (NEW)
**Priority:** Medium
**Effort:** Low
**Description:** The `check_wind_alignment` function has 7 hardcoded sector pairs that were derived once by `scratch/test_sectors.py` from `calvert_zips.geojson`. If the GeoJSON boundaries update, the sectors silently desync. Refactor to derive sector bounds dynamically at startup (or cached on first call) using the same max-gap algorithm already implemented in `test_sectors.py`.
**Why:** Eliminates the manual copy-paste maintenance step and makes the corridor filter robust to GeoJSON updates.

### 1c. Nocturnal / Early-Morning Aggregation Window (NEW)
**Priority:** Medium
**Effort:** Medium
**Description:** All meteorological predictors currently use 24-hour daily averages. Odor trapping is primarily a nocturnal event (inversions form overnight; 8 AM complaint peak). A 10 PM – 10 AM sub-daily aggregation window for BLH, wind speed, and DTR would give the model a sharper trapping signal. Expose as a sidebar option rather than replacing the default. Pairs with Backlog item #3 (Hourly Model).
**Why:** Averaging boundary layer height over the full day (including afternoon convective mixing) significantly dilutes the worst-case trapping signal.

### 2. EPA AQS Monitor Data as Emission Proxy
**Priority:** High  
**Effort:** Medium  
**Description:** Add daily average PM2.5, SO₂, or VOC readings from nearby EPA monitors as an independent emission-intensity predictor variable in the regression models.  
**Why:** This would let the model disentangle "there was more pollution today" from "the weather trapped existing pollution." Currently, the models assume emissions are constant and only weather varies — which is not true.  
**Data needed:**
- Pittsburgh: Allegheny County Health Dept monitors (Liberty, Clairton, Lawrenceville)
- Louisville: LMAPCD monitors (Rubbertown area, Watson Lane)
- Source: [EPA AQS API](https://aqs.epa.gov/aqsweb/documents/data_api.html) or bulk downloads from [EPA Daily Summary Files](https://aqs.epa.gov/aqsweb/airdata/download_files.html)  
**Notes:** A similar approach using bulk downloaded EPA files can be adapted.

---

### 3. Hourly Model with Diurnal Human Activity Weighting (People Asleep)
**Priority:** Medium  
**Effort:** High  
**Description:** Build an hourly-resolution Poisson/Logit model that explicitly accounts for population sleep/wake cycles to address the "people asleep" reporting bias.  
**Approach:**
1. Define a **diurnal activity curve** (e.g., fraction of population awake by hour, sourced from time-use surveys or approximated with a logistic function peaking 8AM–9PM)
2. Use the activity curve as an **offset** in the Poisson model: `log(λ) = Xβ + log(activity_fraction)`
3. Add **time-lagged meteorological predictors** (e.g., BLH and DTR from 3–6 hours prior)
4. Include **hour-of-day** as a cyclical feature (sin/cos encoding)
**Rationale:** Would answer the question "is the 8AM complaint spike because overnight pollution accumulated, or because people just woke up?" The offset approach treats activity as an exposure variable rather than a confounder.

---

### 4. Industrial Shift Change Detection
**Priority:** Medium  
**Effort:** Medium  
**Description:** Add binary indicators for known shift change hours (typically 6AM, 2PM, 10PM for 3-shift operations) to the hourly model (if built).  
**Data needed:**
- Known operating schedules for major emitters:
  - Pittsburgh: Clairton Coke Works (24/7?), US Steel Edgar Thomson Works, Irvin Works
  - Louisville: Rubbertown corridor facilities (LyondellBasell, Hexion, Rohm & Haas, others)
- Shift change times (if publicly available from permits or union contracts)
**Notes:** Even without exact schedules, we could detect shift-change effects empirically by looking for complaint spikes at 6-hour intervals.

---

### 5. Known Emission Event / Flaring Log Integration
**Priority:** Medium  
**Effort:** Low (if data exists)  
**Description:** Incorporate records of known upset events, flaring incidents, or air quality violations as binary predictors or interaction terms.  
**Data needed:**
- ACHD (Allegheny County) violation records for Pittsburgh
- LMAPCD violation/complaint records for Louisville
- State DEP flaring/upset event notifications
**Why:** These are the "spikes" that the current daily model cannot explain with weather alone. A known flaring event on a calm night would explain why complaints were 5x higher than the weather model predicted.

---

### 6. Seasonal Production Cycle Controls
**Priority:** Low  
**Effort:** Low  
**Description:** Add `month` or `quarter` as categorical controls to capture seasonal industrial production patterns that are independent of temperature.  
**Rationale:** Some chemical facilities have seasonal demand cycles (e.g., agricultural chemicals peak in spring, construction materials peak in summer). The current temperature and solar radiation variables partially capture seasonality, but industrial production schedules may add independent variation.  
**Notes:** Risk of multicollinearity with temperature — would need to check VIF before including.

---

### 7. Cross-City Comparative Model
**Priority:** Low  
**Effort:** High  
**Description:** Build a unified model pooling Pittsburgh and Louisville data with city-level fixed effects.  
**Why:** Would test whether the meteorological drivers of odor complaints are universal (generalizable) or city-specific. If DTR and BLH have similar coefficients in both cities, it strengthens the case that atmospheric physics is the primary driver regardless of emission source type.

---

### 8. Public Dashboard Real-Time ORI Prediction
**Priority:** Low (dependent on models being finalized)  
**Effort:** High  
**Description:** Deploy the finalized Logit model behind a web dashboard (using `public_dashboard_mockup.py` as a starting point) that pulls live weather data from Open-Meteo and displays a real-time Odor Risk Index forecast.  
**Dependencies:** Models must be finalized and validated first.

---

### 9. Cross-City Model Mapping & Generalization
**Priority:** High  
**Effort:** Medium  
**Description:** Map/apply the trained Pittsburgh model directly onto Louisville data (and vice-versa) to evaluate how well a model trained in one city predicts odor events in another.  
**Why:** This tests if the model can be generalized to any US city (even those without historical odor complaint records) using only local weather data. 

---

### 10. Complaint Threshold & Binning Sensitivity Analysis
**Priority:** Medium  
**Effort:** Medium  
**Description:** Run a sensitivity analysis on how odor events are binned and classified. Currently, odor events are defined by a threshold (mean weighted odor burden). We need to test other classification criteria:
- No binning (predicting continuous counts directly)
- Binary classification of "odor event day" using:
  - Daily complaints count > 1
  - Daily complaints count >= 3
  - Daily complaints count > 3
- Evaluate which threshold maximizes the model's discriminative performance (AUC, F1-score).

---

### 11. Precipitation Outlier and Data Alignment Review
**Priority:** High  
**Effort:** Low  
**Description:** Investigate the "Odor Complaints vs. Precipitation" plot. There appears to be a major outlier where complaints are very high (almost above 3 on the average scale) during a day with precipitation that is not represented in the Open-Meteo precipitation metrics (where max hourly rain is 0.99 inches). 
**Tasks:**
- Locate the specific date of this outlier.
- Cross-reference with external weather station data to verify if the precipitation reading was correct or if there was a data alignment lag.

---

### 12. Plot Bin Size Optimization
**Priority:** Low  
**Effort:** Low  
**Description:** Optimize the bin sizes for exploratory plots. For variables with high localized variation (like temperature), expand the bin width beyond 1 degree (e.g., to 3-degree or 5-degree bins) to smooth out noise and reveal the underlying physical pattern more clearly.

---

### 13. Spatial Odor Severity Mapping for Source Attribution
**Priority:** High  
**Effort:** High  
**Description:** Use the spatial coordinates (lat/lon) of smell reports, combined with their 1-5 severity values, to pinpoint source locations.
**Approach:** 
- Test if a "distance-decay" pattern exists: are reports closer to the industrial source rated as 5 (highest severity), with 4, 3, 2, 1 extending outward?
- Analyze if reporting patterns match industrial center coordinates or if user reporting bias (e.g., people selecting 1 vs. 5 randomly) confounds the signal.

---

### 14. Industrial Facility Operating Hours & Proximity Features
**Priority:** High  
**Effort:** Medium  
**Description:** Create engineered features representing facility activity and proximity.
**Approach:**
- `is_facility_open`: binary indicator of typical operating hours/schedules for local chemical companies.
- `near_facility`: spatial indicator or weighting factor for zip codes closer to active emitters.
- Evaluate if adding these temporal/spatial facility indicators significantly boosts the predictive power of the model.

---

### 15. Machine Learning Model Comparison
**Priority:** Medium  
**Effort:** Medium  
**Description:** Fit and compare non-linear machine learning models (e.g., Random Forest, XGBoost, Support Vector Regressors) against the classical regression models (OLS, Poisson, Logit).
**Why:** Machine learning models can automatically capture complex, non-linear interactions between weather variables (e.g., wind speed and boundary layer height interactions) without requiring manual interaction terms.
**Goal:** Determine which model type achieves the best cross-validated predictive accuracy.

---

### 16. Deploy Forecasting Dashboard to Streamlit Cloud / GitHub Pages
**Priority:** High  
**Effort:** Medium  
**Description:** Make the forecasting dashboard publicly accessible so paid testers can view real-time risk predictions and report odors directly.  
**Approach:**  
- **Option A:** Deploy the Streamlit app to Streamlit Community Cloud and connect it to a cloud database (e.g., Google Sheets API, Supabase, or PostgreSQL) to store tester feedback.  
- **Option B:** Build a static dashboard compiler that runs via GitHub Actions, uploads predictions to GitHub Pages, and embeds a Google Form to capture tester feedback.

---

## 💡 Research Questions to Investigate

- **Q1:** Is the weekend effect primarily driven by reduced industrial emissions or reduced human outdoor exposure (fewer people outside to notice)?
- **Q2:** Do night-shift workers file more overnight complaints than the general population? (Would need demographic data from Smell Pittsburgh app)
- **Q3:** Is there a "Monday morning effect" where startup emissions after weekend shutdowns produce a distinct spike?
- **Q4:** How do school schedules (summer break vs. school year) affect complaint filing rates independent of temperature?
- **Q5:** Can we detect the COVID-19 lockdown effect on industrial emissions through complaint count changes in March–May 2020?
- **Q6:** **Literature Review:** Has there been other weather-variable analysis published linking local weather station data to odor complaints and air quality indices? Let's check existing publications.

*Last updated: 2026-06-23*
