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

## 🔧 In Progress

*(No items currently in progress)*

---

## 📋 Backlog — Prioritized

### 2. EPA AQS Monitor Data as Emission Proxy
**Priority:** High  
**Effort:** Medium  
**Description:** Add daily average PM2.5, SO₂, or VOC readings from nearby EPA monitors as an independent emission-intensity predictor variable in the regression models.  
**Why:** This would let the model disentangle "there was more pollution today" from "the weather trapped existing pollution." Currently, the models assume emissions are constant and only weather varies — which is not true.  
**Data needed:**
- Pittsburgh: Allegheny County Health Dept monitors (Liberty, Clairton, Lawrenceville)
- Louisville: LMAPCD monitors (Rubbertown area, Watson Lane)
- Source: [EPA AQS API](https://aqs.epa.gov/aqsweb/documents/data_api.html) or bulk downloads from [EPA Daily Summary Files](https://aqs.epa.gov/aqsweb/airdata/download_files.html)  
**Notes:** We already have hourly EPA monitor CSVs for Calvert City in the plume engine (`calvert_plume_engine_one_day.py` lines 33–42). Same approach can be adapted.

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

### 9. Calvert City Model
**Priority:** Medium  
**Effort:** Medium  
**Description:** Adapt the Pittsburgh/Louisville analysis framework to Calvert City, KY, leveraging the HYSPLIT plume dispersion data from the plume engine as an additional independent variable.  
**Data needed:** Smell reports for Calvert City (if they exist in the SmellPGH database) or proxy complaint data from KDAQ.  
**Notes:** The plume engine already models hourly dispersion; could create a "modeled exposure" variable representing predicted ground-level concentration at residential zip codes.

---

### 10. Cross-City Model Mapping & Generalization
**Priority:** High  
**Effort:** Medium  
**Description:** Map/apply the trained Pittsburgh model directly onto Louisville data (and vice-versa) to evaluate how well a model trained in one city predicts odor events in another.  
**Why:** This tests if the model can be generalized to any US city (even those without historical odor complaint records) using only local weather data. 

---

### 11. Complaint Threshold & Binning Sensitivity Analysis
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

### 12. Precipitation Outlier and Data Alignment Review
**Priority:** High  
**Effort:** Low  
**Description:** Investigate the "Odor Complaints vs. Precipitation" plot. There appears to be a major outlier where complaints are very high (almost above 3 on the average scale) during a day with precipitation that is not represented in the Open-Meteo precipitation metrics (where max hourly rain is 0.99 inches). 
**Tasks:**
- Locate the specific date of this outlier.
- Cross-reference with external weather station data to verify if the precipitation reading was correct or if there was a data alignment lag.

---

### 13. Plot Bin Size Optimization
**Priority:** Low  
**Effort:** Low  
**Description:** Optimize the bin sizes for exploratory plots. For variables with high localized variation (like temperature), expand the bin width beyond 1 degree (e.g., to 3-degree or 5-degree bins) to smooth out noise and reveal the underlying physical pattern more clearly.

---

### 14. Spatial Odor Severity Mapping for Source Attribution
**Priority:** High  
**Effort:** High  
**Description:** Use the spatial coordinates (lat/lon) or zip codes of smell reports, combined with their 1-5 severity values, to pinpoint source locations.
**Approach:** 
- Test if a "distance-decay" pattern exists: are reports closer to the industrial source rated as 5 (highest severity), with 4, 3, 2, 1 extending outward?
- Analyze if reporting patterns match industrial center coordinates or if user reporting bias (e.g., people selecting 1 vs. 5 randomly) confounds the signal.

---

### 15. Industrial Facility Operating Hours & Proximity Features
**Priority:** High  
**Effort:** Medium  
**Description:** Create engineered features representing facility activity and proximity.
**Approach:**
- `is_facility_open`: binary indicator of typical operating hours/schedules for local chemical companies.
- `near_facility`: spatial indicator or weighting factor for zip codes closer to active emitters.
- Evaluate if adding these temporal/spatial facility indicators significantly boosts the predictive power of the model.

---

### 16. Machine Learning Model Comparison
**Priority:** Medium  
**Effort:** Medium  
**Description:** Fit and compare non-linear machine learning models (e.g., Random Forest, XGBoost, Support Vector Regressors) against the classical regression models (OLS, Poisson, Logit).
**Why:** Machine learning models can automatically capture complex, non-linear interactions between weather variables (e.g., wind speed and boundary layer height interactions) without requiring manual interaction terms.
**Goal:** Determine which model type achieves the best cross-validated predictive accuracy.

---

## 💡 Research Questions to Investigate

- **Q1:** Is the weekend effect primarily driven by reduced industrial emissions or reduced human outdoor exposure (fewer people outside to notice)?
- **Q2:** Do night-shift workers file more overnight complaints than the general population? (Would need demographic data from Smell Pittsburgh app)
- **Q3:** Is there a "Monday morning effect" where startup emissions after weekend shutdowns produce a distinct spike?
- **Q4:** How do school schedules (summer break vs. school year) affect complaint filing rates independent of temperature?
- **Q5:** Can we detect the COVID-19 lockdown effect on industrial emissions through complaint count changes in March–May 2020?
- **Q6:** **Literature Review:** Has there been other weather-variable analysis published linking local weather station data to odor complaints and air quality indices? Let's check existing publications.

---

*Last updated: 2026-06-17*
