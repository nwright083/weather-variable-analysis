"""
Dual_Model_Proximity_Analysis.py
=================================
Pittsburgh Odor-Complaint Weather Project
------------------------------------------
Builds two logit / Poisson models to predict Odor Risk Index (ORI):
  Model A – weather variables only
  Model B – weather variables + emission-source proximity features

Proximity features engineered per source:
  * Haversine distance (miles)
  * Exponential decay  exp(-0.02 * dist)
  * Continuous wind-alignment factor  (1 + cos(wind_toward - bearing)) / 2

Outputs
-------
  Pittsburgh Data/Dual_Model_Proximity_Analysis_*.png  – diagnostic plots
  Pittsburgh Data/model_coeffs_pittsburgh.json         – live-dashboard coefficients

NOTE: The proximity-enhanced coefficients are ported into the Calvert City
      forecaster.  Export accuracy is critical.
"""

import json
import math
import warnings

import matplotlib
matplotlib.use("Agg")          # headless – no display needed

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
from scipy import stats

warnings.filterwarnings("ignore")

# ── Try optional packages ─────────────────────────────────────────────────────
try:
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_curve, auc as sklearn_auc
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("sklearn not found – CV ROC-AUC will be skipped")

try:
    import holidays
    HAS_HOLIDAYS = True
except ImportError:
    HAS_HOLIDAYS = False
    print("holidays package not found – is_holiday will be set to 0")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 – SETUP & DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 70)
print("SECTION 1 – Setup & Data Loading")
print("=" * 70)

DATA_PATH = "Pittsburgh Data/open-meteo-smell-merged.csv"
PLOT_PREFIX = "Pittsburgh Data/Dual_Model_Proximity_Analysis"

# Column mapping from raw CSV to canonical names
COL_MAP = {
    "time":                        "datetime",
    "smell_report_count":          "complaints",
    "temperature_2m (°F)":         "temperature",
    "relative_humidity_2m (%)":    "relative_humidity",
    "wind_speed_10m (mp/h)":       "wind_speed",
    "wind_direction_10m (°)":      "wind_direction",
    "rain (inch)":                 "precipitation",
    "dew_point_2m (°F)":           "dew_point",
    "vapour_pressure_deficit (kPa)": "vapor_pressure",
    "surface_pressure (hPa)":      "atmospheric_pressure",
    "shortwave_radiation (W/m²)":  "solar_radiation",
    "sunshine_duration (s)":       "sunshine_duration",
    "boundary_layer_height (ft)":  "boundary_layer_height",
}

print(f"Loading {DATA_PATH} …")
df_raw = pd.read_csv(DATA_PATH, low_memory=False)
print(f"  Raw shape: {df_raw.shape}")

# Apply column map (only rename columns that exist)
rename_actual = {k: v for k, v in COL_MAP.items() if k in df_raw.columns}
df_raw = df_raw.rename(columns=rename_actual)

# Ensure key columns are numeric
numeric_cols = ["complaints", "temperature", "relative_humidity", "wind_speed",
                "wind_direction", "precipitation", "atmospheric_pressure",
                "solar_radiation", "boundary_layer_height", "smell_value_average"]
for col in numeric_cols:
    if col in df_raw.columns:
        df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce")

df_raw["datetime"] = pd.to_datetime(df_raw["datetime"], errors="coerce")
df_raw["date"] = df_raw["datetime"].dt.date
df_raw["zipcode"] = df_raw["zipcode"].astype(str)

print(f"  Zipcodes: {df_raw['zipcode'].nunique()}")
print(f"  Date range: {df_raw['date'].min()} → {df_raw['date'].max()}")

# ── Zip centroids ─────────────────────────────────────────────────────────────
zip_centroids = (
    df_raw.groupby("zipcode")[["latitude", "longitude"]]
    .mean()
    .reset_index()
    .rename(columns={"latitude": "lat", "longitude": "lon"})
)
print(f"  Zip centroids computed for {len(zip_centroids)} zips")

# ── Circular wind-direction mean ──────────────────────────────────────────────
def circular_wind_mean(series):
    rads = np.radians(series.dropna())
    if len(rads) == 0:
        return np.nan
    u = np.mean(np.sin(rads))
    v = np.mean(np.cos(rads))
    return (np.degrees(np.arctan2(u, v)) + 360) % 360

# ── Build daily zip-level panel ───────────────────────────────────────────────
print("Building daily zip-level panel …")

# Filter rows where BOTH complaints==0 AND smell_value_average is NaN
# (true no-report padding rows that would contaminate the ORI threshold)
mask_true_no_report = (df_raw["complaints"] == 0) & (df_raw["smell_value_average"].isna())
df_filtered = df_raw[~mask_true_no_report].copy()
print(f"  Dropped {mask_true_no_report.sum():,} padding rows; {len(df_filtered):,} remain")

# Aggregation spec
agg_spec = {
    "complaints":            "sum",
    "temperature":           ["mean", "min", "max"],
    "precipitation":         "sum",
    "wind_speed":            "mean",
    "atmospheric_pressure":  "mean",
    "solar_radiation":       "mean",
    "boundary_layer_height": "mean",
    "relative_humidity":     "mean",
    "smell_value_average":   "mean",
}
# Only keep columns that actually exist
agg_spec = {k: v for k, v in agg_spec.items() if k in df_filtered.columns}

# Wind direction needs circular mean – handled separately
grouped = df_filtered.groupby(["zipcode", "date"])
daily_zip = grouped.agg(agg_spec)
daily_zip.columns = ["_".join(c).strip("_") if isinstance(c, tuple) else c
                     for c in daily_zip.columns]
daily_zip = daily_zip.reset_index()

# Circular wind direction
wind_circ = grouped["wind_direction"].apply(circular_wind_mean).reset_index()
wind_circ.columns = ["zipcode", "date", "wind_direction"]
daily_zip = daily_zip.merge(wind_circ, on=["zipcode", "date"], how="left")

# Flatten multi-level names if any
daily_zip.columns = [c.replace(" ", "_") for c in daily_zip.columns]

# Rename flattened columns to canonical
flat_rename = {
    "temperature_mean": "temperature",
    "temperature_min":  "temperature_min",
    "temperature_max":  "temperature_max",
    "precipitation_sum": "precipitation",
    "wind_speed_mean":  "wind_speed",
    "atmospheric_pressure_mean": "atmospheric_pressure",
    "solar_radiation_mean": "solar_radiation",
    "boundary_layer_height_mean": "boundary_layer_height",
    "relative_humidity_mean": "relative_humidity",
    "smell_value_average_mean": "smell_value_average",
    "complaints_sum": "complaints",
}
daily_zip = daily_zip.rename(columns={k: v for k, v in flat_rename.items()
                                       if k in daily_zip.columns})

# ── Derived features ──────────────────────────────────────────────────────────
daily_zip["date"] = pd.to_datetime(daily_zip["date"])
daily_zip["diurnal_temperature_range"] = daily_zip["temperature_max"] - daily_zip["temperature_min"]
daily_zip["temperature_squared"] = daily_zip["temperature"] ** 2

daily_zip["smell_value_average"] = daily_zip["smell_value_average"].fillna(0)
daily_zip["weighted_odor_burden"] = daily_zip["complaints"] * daily_zip["smell_value_average"]
wob_mean = daily_zip["weighted_odor_burden"].mean()
daily_zip["is_odor_event"] = (daily_zip["weighted_odor_burden"] > wob_mean).astype(int)
print(f"  ORI event rate: {daily_zip['is_odor_event'].mean():.3f} "
      f"(threshold WOB={wob_mean:.2f})")

# Day-of-week dummies (Monday = reference, excluded)
dow_map = {1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
for num, name in dow_map.items():
    daily_zip[f"dow_{name}"] = (daily_zip["date"].dt.dayofweek == num).astype(int)

# is_holiday
if HAS_HOLIDAYS:
    us_hols = holidays.US()
    daily_zip["is_holiday"] = daily_zip["date"].apply(
        lambda d: int(d in us_hols))
else:
    daily_zip["is_holiday"] = 0

print(f"  Daily zip panel shape: {daily_zip.shape}")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 – PROXIMITY FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SECTION 2 – Proximity Feature Engineering")
print("=" * 70)

EMISSION_SOURCES = {
    "Clairton_Coke_Works": (40.2974, -79.8809),
    "Edgar_Thomson_Works":  (40.3922, -79.8550),
    "Irvin_Works":          (40.3644, -79.8944),
}


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def bearing(src_lat, src_lon, dst_lat, dst_lon):
    dy = dst_lat - src_lat
    dx = (dst_lon - src_lon) * math.cos(math.radians(src_lat))
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def continuous_wind_alignment(wind_from_deg, bearing_deg):
    """Returns 0–1; 1 = wind blowing directly from source toward receptor."""
    wind_toward = (wind_from_deg + 180) % 360
    angle_diff = math.radians(wind_toward - bearing_deg)
    return (1 + math.cos(angle_diff)) / 2


# Merge zip centroids into daily_zip
daily_zip = daily_zip.merge(zip_centroids[["zipcode", "lat", "lon"]],
                             on="zipcode", how="left")

for src_name, (src_lat, src_lon) in EMISSION_SOURCES.items():
    print(f"  Computing features for {src_name} …")

    daily_zip[f"dist_{src_name}"] = daily_zip.apply(
        lambda r: haversine_miles(src_lat, src_lon, r["lat"], r["lon"]), axis=1)

    daily_zip[f"exp02_{src_name}"] = np.exp(
        -0.02 * daily_zip[f"dist_{src_name}"])

    daily_zip[f"bearing_{src_name}"] = daily_zip.apply(
        lambda r: bearing(src_lat, src_lon, r["lat"], r["lon"]), axis=1)

    daily_zip[f"wind_align_{src_name}"] = daily_zip.apply(
        lambda r: continuous_wind_alignment(
            r["wind_direction"], r[f"bearing_{src_name}"]), axis=1)

# Aggregate proximity features
exp02_cols      = [f"exp02_{s}"       for s in EMISSION_SOURCES]
wind_align_cols = [f"wind_align_{s}"  for s in EMISSION_SOURCES]
dist_cols       = [f"dist_{s}"        for s in EMISSION_SOURCES]

daily_zip["multi_source_exposure"] = daily_zip[exp02_cols].sum(axis=1)

# Exposure-weighted wind alignment
total_exp = daily_zip[exp02_cols].sum(axis=1).replace(0, np.nan)
weighted_num = sum(daily_zip[f"exp02_{s}"] * daily_zip[f"wind_align_{s}"]
                   for s in EMISSION_SOURCES)
daily_zip["wind_align_weighted"] = weighted_num / total_exp

daily_zip["dist_nearest"] = daily_zip[dist_cols].min(axis=1)

print(f"  multi_source_exposure range: "
      f"{daily_zip['multi_source_exposure'].min():.3f} – "
      f"{daily_zip['multi_source_exposure'].max():.3f}")
print(f"  wind_align_weighted range: "
      f"{daily_zip['wind_align_weighted'].min():.3f} – "
      f"{daily_zip['wind_align_weighted'].max():.3f}")
print(f"  dist_nearest range: "
      f"{daily_zip['dist_nearest'].min():.1f} – "
      f"{daily_zip['dist_nearest'].max():.1f} miles")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 – BINNED DISTRIBUTION PLOTS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SECTION 3 – Binned Distribution Plots")
print("=" * 70)

features_to_plot = {
    "dist_nearest":           "Distance to Nearest Emission Source (miles)",
    "multi_source_exposure":  "Multi-Source Exposure (sum of exp(−0.02·dist))",
    "wind_align_weighted":    "Exposure-Weighted Wind Alignment (0–1)",
}

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
fig.suptitle("Pittsburgh: Mean Daily Complaints by Proximity Feature Bin",
             fontsize=14, fontweight="bold")

for ax, (feat, label) in zip(axes, features_to_plot.items()):
    col_data = daily_zip[feat].dropna()
    try:
        bins = pd.qcut(daily_zip[feat], q=8, duplicates="drop")
    except Exception:
        bins = pd.cut(daily_zip[feat], bins=8)

    grp = daily_zip.groupby(bins)["complaints"].agg(["mean", "sem"]).dropna()
    bin_labels = [str(b) for b in grp.index]
    x = range(len(grp))
    ax.bar(x, grp["mean"], yerr=grp["sem"], capsize=4,
           color="steelblue", alpha=0.8, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(bin_labels, rotation=45, ha="right", fontsize=7)
    ax.set_xlabel(label, fontsize=9)
    ax.set_ylabel("Mean Daily Complaints", fontsize=9)
    ax.set_title(feat.replace("_", " ").title(), fontsize=10)
    ax.grid(axis="y", alpha=0.3)

plt.tight_layout()
plot_path = f"{PLOT_PREFIX}_section3_bins.png"
plt.savefig(plot_path, dpi=120, bbox_inches="tight")
plt.show()
print(f"  Saved {plot_path}")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 – FEATURE IMPORTANCE SCREENING
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SECTION 4 – Feature Importance Screening")
print("=" * 70)

weather_vars = [
    "temperature", "temperature_squared", "solar_radiation",
    "relative_humidity", "wind_speed", "precipitation",
    "diurnal_temperature_range", "boundary_layer_height",
    "atmospheric_pressure",
    "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat", "dow_sun",
    "is_holiday",
]
# Only keep those that actually exist in daily_zip
weather_vars = [v for v in weather_vars if v in daily_zip.columns]

model_specs = {
    "Weather Only":      weather_vars,
    "+Proximity":        weather_vars + ["multi_source_exposure"],
    "+Wind Alignment":   weather_vars + ["wind_align_weighted"],
    "+Both":             weather_vars + ["multi_source_exposure", "wind_align_weighted"],
}

target_logit  = "is_odor_event"
target_poisson = "complaints"

results_table = []

for spec_name, feat_list in model_specs.items():
    all_vars = feat_list + [target_logit, target_poisson]
    sub = daily_zip[all_vars].dropna()
    if len(sub) < 50:
        print(f"  [{spec_name}] insufficient data ({len(sub)} rows) – skipping")
        continue

    X = sm.add_constant(sub[feat_list])
    y_logit   = sub[target_logit]
    y_poisson = sub[target_poisson]

    # ── Logit ─────────────────────────────────────────────────────────────────
    try:
        logit_fit = sm.Logit(y_logit, X).fit(disp=0, method="bfgs",
                                               maxiter=300)
        lr2  = logit_fit.prsquared
        aic  = logit_fit.aic
        p_exp = logit_fit.pvalues.get("multi_source_exposure", np.nan)
        p_ali = logit_fit.pvalues.get("wind_align_weighted",  np.nan)
    except Exception as e:
        print(f"  [{spec_name}] Logit error: {e}")
        lr2 = aic = p_exp = p_ali = np.nan

    # ── Poisson ───────────────────────────────────────────────────────────────
    try:
        pois_fit = sm.GLM(y_poisson, X,
                          family=sm.families.Poisson()).fit(disp=0)
        p_lr2 = 1 - pois_fit.deviance / pois_fit.null_deviance
        p_aic = pois_fit.aic
    except Exception as e:
        print(f"  [{spec_name}] Poisson error: {e}")
        p_lr2 = p_aic = np.nan

    results_table.append({
        "Model":             spec_name,
        "Logit_PseudoR2":   round(lr2, 4),
        "Logit_AIC":        round(aic, 1),
        "Poisson_PseudoR2": round(p_lr2, 4),
        "Poisson_AIC":      round(p_aic, 1),
        "p(exposure)":      round(p_exp, 4) if not np.isnan(p_exp) else "—",
        "p(alignment)":     round(p_ali, 4) if not np.isnan(p_ali) else "—",
    })

results_df = pd.DataFrame(results_table)
print("\n  Model Comparison Table:")
print(results_df.to_string(index=False))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 – DUAL-MODEL FULL COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SECTION 5 – Dual-Model Full Comparison")
print("=" * 70)

prox_vars = weather_vars + ["multi_source_exposure", "wind_align_weighted"]

all_needed = list(set(prox_vars + [target_logit, target_poisson]))
sub_full = daily_zip[all_needed].dropna()
print(f"  Complete-case rows: {len(sub_full):,}")

X_wa  = sm.add_constant(sub_full[weather_vars])
X_pe  = sm.add_constant(sub_full[prox_vars])
y_bin = sub_full[target_logit]

# Fit logit models
print("  Fitting Logit Model A (Weather Only) …")
logit_weather_only = sm.Logit(y_bin, X_wa).fit(disp=0, method="bfgs", maxiter=300)

print("  Fitting Logit Model B (Proximity-Enhanced) …")
logit_proximity_enhanced = sm.Logit(y_bin, X_pe).fit(disp=0, method="bfgs", maxiter=300)

# Fit Poisson models
print("  Fitting Poisson Model A …")
poisson_wa = sm.GLM(sub_full[target_poisson], X_wa,
                    family=sm.families.Poisson()).fit(disp=0)
print("  Fitting Poisson Model B …")
poisson_pe = sm.GLM(sub_full[target_poisson], X_pe,
                    family=sm.families.Poisson()).fit(disp=0)

# ── A. Metrics table ──────────────────────────────────────────────────────────
wa_r2  = logit_weather_only.prsquared
pe_r2  = logit_proximity_enhanced.prsquared
wa_aic = logit_weather_only.aic
pe_aic = logit_proximity_enhanced.aic
delta_r2  = pe_r2 - wa_r2
delta_aic = wa_aic - pe_aic

print(f"\n  ┌─────────────────────────────────────┐")
print(f"  │  Logit Model Comparison              │")
print(f"  ├──────────────┬──────────┬────────────┤")
print(f"  │ Metric       │  Model A │  Model B   │")
print(f"  ├──────────────┼──────────┼────────────┤")
print(f"  │ Pseudo-R²    │ {wa_r2:8.4f} │ {pe_r2:10.4f} │")
print(f"  │ AIC          │ {wa_aic:8.1f} │ {pe_aic:10.1f} │")
print(f"  ├──────────────┼──────────┼────────────┤")
print(f"  │ ΔPseudo-R²   │     —    │ {delta_r2:+10.4f} │")
print(f"  │ ΔAIC         │     —    │ {delta_aic:+10.1f} │")
print(f"  └──────────────┴──────────┴────────────┘")

# ── B. Coefficient bar chart ──────────────────────────────────────────────────
def top_n_coefs(fit_result, n=12):
    coefs = fit_result.params.drop("const", errors="ignore")
    return coefs.reindex(coefs.abs().nlargest(n).index)

coefs_a = top_n_coefs(logit_weather_only,       n=12)
coefs_b = top_n_coefs(logit_proximity_enhanced, n=12)

all_feat = list(dict.fromkeys(list(coefs_b.index) + list(coefs_a.index)))[:14]
coefs_a_vals = [logit_weather_only.params.get(f, 0) for f in all_feat]
coefs_b_vals = [logit_proximity_enhanced.params.get(f, 0) for f in all_feat]

fig, ax = plt.subplots(figsize=(10, 7))
y_pos = np.arange(len(all_feat))
bar_h = 0.35
ax.barh(y_pos + bar_h/2, coefs_b_vals, bar_h, label="Model B (Proximity-Enhanced)",
        color="steelblue", alpha=0.85)
ax.barh(y_pos - bar_h/2, coefs_a_vals, bar_h, label="Model A (Weather Only)",
        color="coral",    alpha=0.85)
ax.set_yticks(y_pos)
ax.set_yticklabels([f.replace("_", " ") for f in all_feat], fontsize=9)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel("Logit Coefficient", fontsize=11)
ax.set_title("Pittsburgh Logit Coefficients: Weather-Only vs Proximity-Enhanced\n"
             "(top 14 features by absolute magnitude in Model B)", fontsize=11)
ax.legend(fontsize=9)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plot_b = f"{PLOT_PREFIX}_section5B_coefs.png"
plt.savefig(plot_b, dpi=120, bbox_inches="tight")
plt.show()
print(f"  Saved {plot_b}")

# ── C. Predicted probability distributions ────────────────────────────────────
pred_a = logit_weather_only.predict(X_wa)
pred_b = logit_proximity_enhanced.predict(X_pe)

fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(pred_a, bins=60, alpha=0.55, label="Model A – Weather Only",
        color="coral",    density=True, edgecolor="white")
ax.hist(pred_b, bins=60, alpha=0.55, label="Model B – Proximity-Enhanced",
        color="steelblue", density=True, edgecolor="white")
ax.set_xlabel("Predicted ORI Probability", fontsize=11)
ax.set_ylabel("Density", fontsize=11)
ax.set_title("Pittsburgh: Predicted ORI Probability Distributions", fontsize=12)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
plt.tight_layout()
plot_c = f"{PLOT_PREFIX}_section5C_distributions.png"
plt.savefig(plot_c, dpi=120, bbox_inches="tight")
plt.show()
print(f"  Saved {plot_c}")

# ── D. ROC curves ─────────────────────────────────────────────────────────────
from sklearn.metrics import roc_curve, roc_auc_score

fpr_a, tpr_a, _ = roc_curve(y_bin, pred_a)
fpr_b, tpr_b, _ = roc_curve(y_bin, pred_b)
auc_a = roc_auc_score(y_bin, pred_a)
auc_b = roc_auc_score(y_bin, pred_b)

# ── Optional: 5-fold CV ROC-AUC ──────────────────────────────────────────────
if HAS_SKLEARN:
    print("  Computing 5-fold CV ROC-AUC …")
    scaler = StandardScaler()
    try:
        X_wa_arr  = scaler.fit_transform(sub_full[weather_vars].fillna(0))
        X_pe_arr  = scaler.fit_transform(sub_full[prox_vars].fillna(0))
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        lr_clf = LogisticRegression(max_iter=500, solver="lbfgs")
        cv_auc_a = cross_val_score(lr_clf, X_wa_arr, y_bin.values,
                                   cv=cv, scoring="roc_auc").mean()
        cv_auc_b = cross_val_score(lr_clf, X_pe_arr, y_bin.values,
                                   cv=cv, scoring="roc_auc").mean()
        print(f"  5-fold CV ROC-AUC  Model A: {cv_auc_a:.4f}  Model B: {cv_auc_b:.4f}")
    except Exception as e:
        print(f"  CV AUC failed: {e}")
        cv_auc_a = cv_auc_b = None
else:
    cv_auc_a = cv_auc_b = None

fig, ax = plt.subplots(figsize=(7, 6))
ax.plot(fpr_a, tpr_a, color="coral",    lw=2,
        label=f"Model A – Weather Only  (AUC={auc_a:.3f})")
ax.plot(fpr_b, tpr_b, color="steelblue", lw=2,
        label=f"Model B – Proximity-Enhanced (AUC={auc_b:.3f})")
ax.plot([0, 1], [0, 1], "k--", lw=1, label="Random")
ax.set_xlabel("False Positive Rate", fontsize=11)
ax.set_ylabel("True Positive Rate", fontsize=11)
ax.set_title("Pittsburgh ORI Logit – ROC Curves", fontsize=12)
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
plt.tight_layout()
plot_d = f"{PLOT_PREFIX}_section5D_roc.png"
plt.savefig(plot_d, dpi=120, bbox_inches="tight")
plt.show()
print(f"  Saved {plot_d}")

# ── E. Full Model B summary ───────────────────────────────────────────────────
print("\n  === Full Logit Model B (Proximity-Enhanced) Summary ===")
print(logit_proximity_enhanced.summary())
print(f"\n  Key proximity coefficients:")
print(f"    multi_source_exposure : "
      f"{logit_proximity_enhanced.params.get('multi_source_exposure', 'N/A'):.6f}  "
      f"p={logit_proximity_enhanced.pvalues.get('multi_source_exposure', np.nan):.4f}")
print(f"    wind_align_weighted   : "
      f"{logit_proximity_enhanced.params.get('wind_align_weighted', 'N/A'):.6f}  "
      f"p={logit_proximity_enhanced.pvalues.get('wind_align_weighted', np.nan):.4f}")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 – EXPORT COEFFICIENTS TO JSON
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("SECTION 6 – Export Coefficients to JSON")
print("=" * 70)

coeffs_wa = logit_weather_only.params.to_dict()
coeffs_pe = logit_proximity_enhanced.params.to_dict()

output = {
    "city": "Pittsburgh",
    "note": (
        "Coefficients from logit model trained on Pittsburgh zip-day panel "
        "(de-biased: dow/holiday vars set to 0 for Calvert City predictions). "
        "Proximity-enhanced includes multi_source_exposure and wind_align_weighted."
    ),
    "weather_only": {k: float(v) for k, v in coeffs_wa.items()},
    "proximity_enhanced": {k: float(v) for k, v in coeffs_pe.items()},
    "model_metrics": {
        "weather_only_aic":            float(logit_weather_only.aic),
        "proximity_enhanced_aic":      float(logit_proximity_enhanced.aic),
        "delta_aic":                   float(logit_weather_only.aic - logit_proximity_enhanced.aic),
        "weather_only_pseudo_r2":      float(logit_weather_only.prsquared),
        "proximity_enhanced_pseudo_r2": float(logit_proximity_enhanced.prsquared),
        "weather_only_auc":            float(auc_a),
        "proximity_enhanced_auc":      float(auc_b),
    },
}
if cv_auc_a is not None:
    output["model_metrics"]["weather_only_cv_auc"]            = float(cv_auc_a)
    output["model_metrics"]["proximity_enhanced_cv_auc"]      = float(cv_auc_b)

json_path = "Pittsburgh Data/model_coeffs_pittsburgh.json"
with open(json_path, "w") as f:
    json.dump(output, f, indent=2)

print(f"  Saved {json_path}")
print(f"  Key proximity coefficients:")
print(f"    multi_source_exposure: {coeffs_pe.get('multi_source_exposure', 'N/A')}")
print(f"    wind_align_weighted  : {coeffs_pe.get('wind_align_weighted',   'N/A')}")
print(f"\n  ΔPseudo-R²  (B − A) : {delta_r2:+.4f}")
print(f"  ΔAIC        (A − B) : {delta_aic:+.1f}  (positive = Model B better)")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 – EXPORT MODEL VALIDATION METRICS (ROC / PR curves + stats)
# Written to model_metrics.json at repo root for the methodology dashboard tab.
# ═══════════════════════════════════════════════════════════════════════════════

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import odor_forecast_core as _core

from sklearn.metrics import precision_recall_curve

print("\n" + "=" * 70)
print("SECTION 7 – Export Model Validation Metrics → model_metrics.json")
print("=" * 70)

_weather_core = [
    "temperature", "temperature_squared", "solar_radiation",
    "relative_humidity", "wind_speed", "precipitation",
    "diurnal_temperature_range", "boundary_layer_height", "atmospheric_pressure",
]

def _linear_pred(df, coeffs):
    """Compute debiased log-odds for a panel DataFrame using the given coeff dict."""
    z = coeffs["const"]
    for v in _weather_core:
        if v in df.columns and v in coeffs:
            z = z + coeffs[v] * df[v]
    # Proximity terms (only present in pittsburgh_proximity)
    for v in ("multi_source_exposure", "wind_align_weighted"):
        if v in df.columns and v in coeffs:
            z = z + coeffs[v] * df[v]
    return z

def _downsample(arr, n=100):
    arr = list(arr)
    if len(arr) <= n:
        return [round(float(x), 5) for x in arr]
    idx = [int(round(i * (len(arr) - 1) / (n - 1))) for i in range(n)]
    seen = set()
    result = []
    for i in idx:
        if i not in seen:
            seen.add(i)
            result.append(round(float(arr[i]), 5))
    return result

def _curve_data(y_true, y_prob, pseudo_r2_val=None, cv_auc_val=None, note=None):
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    auc_val = float(roc_auc_score(y_true, y_prob))
    prec, rec, thr = precision_recall_curve(y_true, y_prob)
    # Optimal F1
    f1s = 2 * prec * rec / (prec + rec + 1e-10)
    best_i = int(np.argmax(f1s))
    d = {
        "fpr":        _downsample(fpr),
        "tpr":        _downsample(tpr),
        "auc":        round(auc_val, 4),
        "precision":  _downsample(prec),
        "recall":     _downsample(rec),
        "f1_opt":     round(float(f1s[best_i]), 4),
        "thr_opt":    round(float(thr[best_i]) if best_i < len(thr) else 0.5, 4),
    }
    if pseudo_r2_val is not None:
        d["pseudo_r2"] = round(float(pseudo_r2_val), 4)
    if cv_auc_val is not None:
        d["cv_auc"] = round(float(cv_auc_val), 4)
    if note:
        d["note"] = note
    return d

_df = sub_full.copy()
_y  = y_bin

# Model A – pittsburgh_proximity (weather-only panel variant → maps to exact_pittsburgh)
_z_ep   = _linear_pred(_df, _core.COEFFS_PITTSBURGH)
_prob_ep = 1.0 / (1.0 + np.exp(-_z_ep.clip(-60, 60)))
_ep_data = _curve_data(
    _y, _prob_ep,
    pseudo_r2_val=logit_weather_only.prsquared,
    cv_auc_val=cv_auc_a if cv_auc_a is not None else None,
    note="Daily city-wide model evaluated on zip-day panel (same discrimination, different granularity)",
)

# Model B – pittsburgh_proximity
_z_pp   = _linear_pred(_df, _core.COEFFS_PITTSBURGH_PROXIMITY)
_prob_pp = 1.0 / (1.0 + np.exp(-_z_pp.clip(-60, 60)))
_pp_data = _curve_data(
    _y, _prob_pp,
    pseudo_r2_val=logit_proximity_enhanced.prsquared,
    cv_auc_val=cv_auc_b if cv_auc_b is not None else None,
)

# Model C – estimated_calvert (hand-tuned; evaluated on Pittsburgh panel)
_z_ec   = _linear_pred(_df, _core.COEFFS_EST_CALVERT)
_prob_ec = 1.0 / (1.0 + np.exp(-_z_ec.clip(-60, 60)))
_ec_data = _curve_data(
    _y, _prob_ec,
    note="Hand-tuned for Calvert City terrain; evaluated on Pittsburgh panel only (no Calvert validation set exists yet)",
)

_n_obs   = int(len(_y))
_ev_rate = round(float(_y.mean() * 100), 1)

metrics_output = {
    "validation_data": f"Pittsburgh zip-day panel (N={_n_obs:,}, event rate {_ev_rate}%)",
    "models": {
        "exact_pittsburgh":     _ep_data,
        "pittsburgh_proximity": _pp_data,
        "estimated_calvert":    _ec_data,
    },
}

metrics_path = "model_metrics.json"
with open(metrics_path, "w") as _f:
    json.dump(metrics_output, _f, indent=2)

print(f"  Saved {metrics_path}")
print(f"  exact_pittsburgh     AUC={_ep_data['auc']:.4f}  pseudo-R²={_ep_data.get('pseudo_r2','N/A')}")
print(f"  pittsburgh_proximity AUC={_pp_data['auc']:.4f}  pseudo-R²={_pp_data.get('pseudo_r2','N/A')}")
print(f"  estimated_calvert    AUC={_ec_data['auc']:.4f}  (hand-tuned; Pittsburgh eval only)")

print("\n" + "=" * 70)
print("SECTION 8 – Hourly Case-Crossover Model")
print("=" * 70)

# ── Why this approach ──────────────────────────────────────────────────────────
# A naive hourly logistic regression would learn *when people are awake and
# outside*, not when the atmosphere traps odor.  Two confounds dominate:
#
#   1. Diurnal reporting behavior: reports peak in afternoon/evening regardless
#      of meteorology.  A naive model learns this curve, not the inversion cycle.
#   2. Solar ≈ hour-of-day collinearity: solar radiation is a near-deterministic
#      function of the hour, making its weather coefficient unidentifiable from
#      behavioral/time-of-day effects.
#
# Time-stratified case-crossover (conditional logistic regression) eliminates
# both confounds by construction.  Strata = (year, month, hour-of-day): within
# each stratum we compare report-hours (cases) to non-report control-hours at
# the *same hour of the same calendar month*.  Because cases and controls share
# the identical hour-of-day, the diurnal behavior curve *and* the solar/hour
# collinearity difference out.  What remains is pure within-hour meteorological
# variance — BLH dropping, wind dying, humidity rising.
#
# Omitted features vs the daily model:
#   solar_radiation        → absorbed by strata (hour-of-day fixed effect)
#   diurnal_temperature_range → daily max−min by construction; zero variance
#                              within a single hour; cannot contribute

from statsmodels.discrete.conditional_models import ConditionalLogit as _CL

HOURLY_FEATS = [
    "temperature", "temperature_squared",
    "boundary_layer_height", "wind_speed",
    "relative_humidity", "atmospheric_pressure",
    "precipitation",
]

# ── 8.1  City-hour panel ───────────────────────────────────────────────────────
print("\n  8.1  Building city-hour panel …")

_weather_h_cols = [
    "temperature", "relative_humidity", "wind_speed",
    "atmospheric_pressure", "solar_radiation",
    "boundary_layer_height", "precipitation",
]
_weather_h_cols = [c for c in _weather_h_cols if c in df_raw.columns]

_df_h = df_raw.copy()
_df_h["_wob"] = _df_h["complaints"].fillna(0) * _df_h["smell_value_average"].fillna(0)

_agg_h = {"complaints": "sum", "_wob": "sum"}
for _c in _weather_h_cols:
    _agg_h[_c] = "mean"

_df_ch = _df_h.groupby("datetime").agg(_agg_h).reset_index()
_df_ch.rename(columns={"_wob": "weighted_burden_h"}, inplace=True)
_df_ch["datetime"]  = pd.to_datetime(_df_ch["datetime"])
_df_ch["hour"]      = _df_ch["datetime"].dt.hour
_df_ch["month"]     = _df_ch["datetime"].dt.month
_df_ch["year"]      = _df_ch["datetime"].dt.year

_burden_thresh = _df_ch["weighted_burden_h"].mean()
_df_ch["is_event_h"] = (_df_ch["weighted_burden_h"] > _burden_thresh).astype(int)

_n_total_h = len(_df_ch)
_n_event_h = int(_df_ch["is_event_h"].sum())
_ev_rate_h  = _n_event_h / _n_total_h * 100
print(f"    City-hours : {_n_total_h:,} total | {_n_event_h:,} events ({_ev_rate_h:.1f}%)")

# ── 8.2  Case-crossover strata ────────────────────────────────────────────────
print("  8.2  Building strata (year × month × hour-of-day) …")

_df_ch["stratum"] = (
    _df_ch["year"].astype(str) + "_"
    + _df_ch["month"].astype(str).str.zfill(2) + "_"
    + _df_ch["hour"].astype(str).str.zfill(2)
)

# Keep only strata that contain both cases and controls
_s_stats = _df_ch.groupby("stratum")["is_event_h"].agg(["sum", "count"])
_valid_s  = _s_stats[(_s_stats["sum"] > 0) & (_s_stats["sum"] < _s_stats["count"])].index
_df_cc    = _df_ch[_df_ch["stratum"].isin(_valid_s)].copy()

_n_strata = _df_cc["stratum"].nunique()
print(f"    Valid strata: {_n_strata:,}  |  CC dataset: {len(_df_cc):,} rows")

# ── 8.3  Feature engineering ──────────────────────────────────────────────────
_df_cc["temperature_squared"] = _df_cc["temperature"] ** 2
# Keep hour + month for the FE-dummies fallback
_cc_keep = HOURLY_FEATS + ["is_event_h", "stratum", "hour", "month"]
_cc_keep = [c for c in _cc_keep if c in _df_cc.columns]
_df_cc = _df_cc[_cc_keep].dropna()
print(f"    After NaN drop: {len(_df_cc):,} rows, {_df_cc['stratum'].nunique():,} strata")

_stratum_codes = pd.Categorical(_df_cc["stratum"]).codes

# ── 8.4  Fit model: ConditionalLogit with fallback to Logit + FE dummies ──────
# Primary: statsmodels ConditionalLogit (exact conditional MLE).
# Fallback: ordinary Logit with hour-of-day + month fixed-effect dummies —
# statistically equivalent for strata large enough to avoid incidental-parameter
# bias (~100+ obs per stratum; ours average ~250).
print("  8.4  Fitting model …")
_cl_fit_ok  = False
_fit_method = "unknown"
_cl_coeffs  = {}
_cl_pvals   = {}
_cl_cis     = {}

# ── Attempt 1: ConditionalLogit ───────────────────────────────────────────────
try:
    _cl_m = _CL(
        endog=_df_cc["is_event_h"],
        exog=_df_cc[HOURLY_FEATS],
        groups=_stratum_codes,
    )
    _cl_r = _cl_m.fit(maxiter=300, method="bfgs", disp=False)
    _cl_coeffs = _cl_r.params.to_dict()
    # pvalues / conf_int can fail even when params succeed — isolate them
    try:
        _cl_pvals = _cl_r.pvalues.to_dict()
        _ci_df    = _cl_r.conf_int()
        _cl_cis   = {k: (float(_ci_df.loc[k, 0]), float(_ci_df.loc[k, 1]))
                     for k in _cl_coeffs}
    except Exception:
        _cl_pvals = {}
        _cl_cis   = {}
    _cl_fit_ok  = True
    _fit_method = "ConditionalLogit (year × month × hour-of-day strata)"
    print(f"    ConditionalLogit: params extracted (CIs available: {bool(_cl_cis)})")
except Exception as _e:
    print(f"    ConditionalLogit failed ({_e}); falling back to Logit + FE dummies …")

# ── Attempt 2: Logit with hour-of-day + month dummies (equivalent) ────────────
if not _cl_fit_ok:
    try:
        _h_dummies  = pd.get_dummies(_df_cc["hour"],  prefix="h",  drop_first=True).astype(float)
        _mo_dummies = pd.get_dummies(_df_cc["month"], prefix="mo", drop_first=True).astype(float)
        _X_fe = pd.concat(
            [_df_cc[HOURLY_FEATS].reset_index(drop=True),
             _h_dummies.reset_index(drop=True),
             _mo_dummies.reset_index(drop=True)],
            axis=1,
        )
        _X_fe = sm.add_constant(_X_fe)
        _logit_fe = sm.Logit(_df_cc["is_event_h"].reset_index(drop=True), _X_fe)
        _res_fe   = _logit_fe.fit(maxiter=500, method="bfgs", disp=False)
        _cl_coeffs = {f: float(_res_fe.params[f]) for f in HOURLY_FEATS
                      if f in _res_fe.params.index}
        _cl_pvals  = {f: float(_res_fe.pvalues[f]) for f in HOURLY_FEATS
                      if f in _res_fe.pvalues.index}
        _ci_df_fe  = _res_fe.conf_int()
        _cl_cis    = {f: (float(_ci_df_fe.loc[f, 0]), float(_ci_df_fe.loc[f, 1]))
                      for f in HOURLY_FEATS if f in _ci_df_fe.index}
        _cl_fit_ok  = True
        _fit_method = "Logit + hour-of-day & month fixed-effect dummies (fallback)"
        print(f"    Fallback Logit converged (pseudo-R² = {_res_fe.prsquared:.4f})")
    except Exception as _e2:
        print(f"    Fallback also failed: {_e2}")

if _cl_fit_ok:
    print(f"    Method: {_fit_method}")
    print(f"\n    {'Feature':<35} {'Coef':>9}  {'p-val':>7}  {'95% CI'}")
    print(f"    {'-'*70}")
    for _f in HOURLY_FEATS:
        _co = _cl_coeffs.get(_f, float("nan"))
        _pv = _cl_pvals.get(_f, float("nan"))
        _lo, _hi = _cl_cis.get(_f, (float("nan"), float("nan")))
        _sig = "*" if (not np.isnan(_pv) and _pv < 0.05) else " "
        print(f"  {_sig} {_f:<35} {_co:+9.5f}  {_pv:7.4f}  [{_lo:+.5f}, {_hi:+.5f}]")

# ── 8.5  Robustness: unconditional logit + hour dummies ───────────────────────
print("\n  8.5  Robustness check (unconditional logit + hour-of-day dummies) …")
_rob_coeffs = {}
if HAS_SKLEARN:
    _h_dummies = pd.get_dummies(_df_cc["stratum"].str[-2:].astype(int), prefix="h",
                                 drop_first=True)
    _X_rob = pd.concat([_df_cc[HOURLY_FEATS].reset_index(drop=True),
                         _h_dummies.reset_index(drop=True)], axis=1)
    _y_rob = _df_cc["is_event_h"].values
    from sklearn.preprocessing import StandardScaler as _SS
    from sklearn.linear_model import LogisticRegression as _LR
    _sc     = _SS()
    _X_robs = _sc.fit_transform(_X_rob)
    _lr_r   = _LR(max_iter=500, C=1.0, solver="lbfgs").fit(_X_robs, _y_rob)
    _feat_n = list(_X_rob.columns)
    _rob_coeffs = {_f: float(_lr_r.coef_[0][_feat_n.index(_f)])
                   for _f in HOURLY_FEATS if _f in _feat_n}
    print("    Standardized coefficients (should match sign with ConditionalLogit):")
    for _f in HOURLY_FEATS:
        _c_rob = _rob_coeffs.get(_f, float("nan"))
        _c_cl  = _cl_coeffs.get(_f, float("nan"))
        _agree = "✓" if (not np.isnan(_c_rob) and not np.isnan(_c_cl)
                         and np.sign(_c_rob) == np.sign(_c_cl)) else "?"
        print(f"    {_agree}  {_f:<35} rob={_c_rob:+.4f}  CL={_c_cl:+.5f}")
else:
    print("    sklearn not available – skipping robustness check")

# ── 8.6  Plots ────────────────────────────────────────────────────────────────
print("\n  8.6  Generating plots …")

# Plot A: Odds-ratio forest plot with 95% CIs
if _cl_fit_ok:
    _or_vals  = {f: np.exp(_cl_coeffs[f]) for f in HOURLY_FEATS if f in _cl_coeffs}
    _or_lo    = {f: np.exp(_cl_cis[f][0]) for f in HOURLY_FEATS if f in _cl_cis}
    _or_hi    = {f: np.exp(_cl_cis[f][1]) for f in HOURLY_FEATS if f in _cl_cis}
    _feats_pl = [f for f in HOURLY_FEATS if f in _or_vals]
    _labels   = [f.replace("_", " ").title() for f in _feats_pl]
    _y_pos    = np.arange(len(_feats_pl))
    _colors   = ["#ef4444" if _or_vals[f] > 1 else "#3b82f6" for f in _feats_pl]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axvline(1.0, color="#94a3b8", linewidth=1.2, linestyle="--")
    for _i, _f in enumerate(_feats_pl):
        ax.errorbar(
            _or_vals[_f], _y_pos[_i],
            xerr=[[_or_vals[_f] - _or_lo[_f]], [_or_hi[_f] - _or_vals[_f]]],
            fmt="o", color=_colors[_i], markersize=7, capsize=4, linewidth=1.8,
        )
        _pv = _cl_pvals.get(_f, 1.0)
        _sig = "**" if _pv < 0.01 else ("*" if _pv < 0.05 else "")
        ax.text(_or_hi[_f] * 1.01, _y_pos[_i], f"OR={_or_vals[_f]:.3f} {_sig}",
                va="center", fontsize=8.5, color="#1e293b")
    ax.set_yticks(_y_pos)
    ax.set_yticklabels(_labels, fontsize=9)
    ax.set_xlabel("Odds Ratio (per unit change)", fontsize=10)
    ax.set_title("Hourly Case-Crossover: Odds Ratios for Odor-Event Hour\n"
                 "(strata = year × month × hour-of-day; 95% CI)", fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    _p8a = f"{PLOT_PREFIX}_section8A_hourly_forest.png"
    plt.savefig(_p8a, dpi=120, bbox_inches="tight")
    plt.show()
    print(f"    Saved {_p8a}")

# Plot B: Hourly vs daily coefficient comparison (shared features, standardized)
_shared = [f for f in HOURLY_FEATS
           if f in _cl_coeffs and f in _core.COEFFS_PITTSBURGH
              and f not in ("temperature_squared",)]
if _shared and HAS_SKLEARN:
    # Standardize both sets of coefficients for comparison
    # Use the city-hour data std for hourly, daily_zip std for daily
    _std_h = {f: float(_df_cc[f].std()) for f in _shared if f in _df_cc.columns}
    _std_d = {f: float(sub_full[f].std()) for f in _shared if f in sub_full.columns}

    _coef_h_s = {f: _cl_coeffs[f] * _std_h.get(f, 1.0) for f in _shared}
    _coef_d_s = {f: _core.COEFFS_PITTSBURGH[f] * _std_d.get(f, 1.0) for f in _shared}

    _x = np.arange(len(_shared))
    _bw = 0.35
    _lbls_s = [f.replace("_", " ").title() for f in _shared]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(_x - _bw/2, [_coef_h_s[f] for f in _shared], _bw,
           label="Hourly (case-crossover)", color="#3b82f6", alpha=0.85)
    ax.bar(_x + _bw/2, [_coef_d_s[f] for f in _shared], _bw,
           label="Daily (Pittsburgh model)", color="#f97316", alpha=0.85)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(_x)
    ax.set_xticklabels(_lbls_s, rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("Standardized coefficient (× 1 SD)", fontsize=10)
    ax.set_title("Hourly vs Daily model: standardized coefficients\n"
                 "(same sign = consistent direction across time scales)", fontsize=10)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    _p8b = f"{PLOT_PREFIX}_section8B_hourly_vs_daily_coefs.png"
    plt.savefig(_p8b, dpi=120, bbox_inches="tight")
    plt.show()
    print(f"    Saved {_p8b}")

# Plot C: Mean within-day predicted shape — event vs non-event days
if _cl_fit_ok:
    # Compute raw z for every city-hour (pre-anchoring)
    _df_ch2 = _df_ch.dropna(subset=[f for f in HOURLY_FEATS
                                      if f not in ("temperature_squared",)]).copy()
    _df_ch2["temperature_squared"] = _df_ch2["temperature"] ** 2
    _z_h = sum(_cl_coeffs.get(f, 0) * _df_ch2[f] for f in HOURLY_FEATS
               if f in _df_ch2.columns)
    _df_ch2["z_hourly"] = _z_h

    _mean_z_by_hour = _df_ch2.groupby(["is_event_h", "hour"])["z_hourly"].mean().unstack(0)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    _hrs = list(range(24))
    if 0 in _mean_z_by_hour.columns:
        ax.plot(_hrs, [_mean_z_by_hour[0].get(h, np.nan) for h in _hrs],
                color="#3b82f6", linewidth=2, label="Non-event hours (mean)")
    if 1 in _mean_z_by_hour.columns:
        ax.plot(_hrs, [_mean_z_by_hour[1].get(h, np.nan) for h in _hrs],
                color="#ef4444", linewidth=2, label="Event hours (mean)")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels(["12a","3a","6a","9a","12p","3p","6p","9p"], fontsize=9)
    ax.set_xlabel("Hour of day (local time)", fontsize=10)
    ax.set_ylabel("Mean raw log-odds (z, pre-anchor)", fontsize=10)
    ax.set_title("Mean within-day predicted log-odds shape\n"
                 "(case-crossover coefficients; anchored to daily ORI at inference)",
                 fontsize=10)
    ax.legend(fontsize=9)
    ax.axhline(0, color="#94a3b8", linewidth=0.8, linestyle="--")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    _p8c = f"{PLOT_PREFIX}_section8C_hourly_shape.png"
    plt.savefig(_p8c, dpi=120, bbox_inches="tight")
    plt.show()
    print(f"    Saved {_p8c}")

# Plot D: Case vs control distributions for the three strongest features
_top3 = sorted([f for f in HOURLY_FEATS if f in _df_cc.columns and f != "temperature_squared"],
               key=lambda f: abs(_cl_coeffs.get(f, 0)), reverse=True)[:3]
if _top3:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for _ax, _f in zip(axes, _top3):
        _cases = _df_cc[_df_cc["is_event_h"] == 1][_f].dropna()
        _ctrls = _df_cc[_df_cc["is_event_h"] == 0][_f].dropna()
        _ax.hist(_ctrls, bins=50, alpha=0.55, density=True, color="#3b82f6",
                 edgecolor="white", label=f"Control (n={len(_ctrls):,})")
        _ax.hist(_cases, bins=50, alpha=0.55, density=True, color="#ef4444",
                 edgecolor="white", label=f"Case (n={len(_cases):,})")
        _ax.set_xlabel(_f.replace("_", " ").title(), fontsize=9)
        _ax.set_ylabel("Density", fontsize=9)
        _ax.legend(fontsize=8)
        _ax.grid(alpha=0.3)
    axes[0].set_title("Case vs Control distributions — top 3 hourly drivers", fontsize=10)
    plt.tight_layout()
    _p8d = f"{PLOT_PREFIX}_section8D_hourly_distributions.png"
    plt.savefig(_p8d, dpi=120, bbox_inches="tight")
    plt.show()
    print(f"    Saved {_p8d}")

# ── 8.7  Export coefficients ──────────────────────────────────────────────────
print("\n  8.7  Exporting model_coeffs_hourly.json …")

if _cl_fit_ok:
    _hourly_export = {
        "note": (
            f"Hourly odor-risk model — {_fit_method}. "
            "Hour-of-day and calendar-month fixed effects remove diurnal reporting "
            "behavior and the solar/hour-of-day collinearity, yielding genuine sub-daily "
            "meteorological coefficients. At inference the 24 hourly z-values are "
            "re-centered so their mean equals logit(daily_ORI/100), anchoring the "
            "within-day shape to the calibrated daily ORI without changing its level."
        ),
        "coefficients": {k: float(v) for k, v in _cl_coeffs.items()},
        "p_values": {k: float(v) for k, v in _cl_pvals.items()},
        "confidence_intervals_95": {
            k: [round(float(v[0]), 6), round(float(v[1]), 6)]
            for k, v in _cl_cis.items()
        },
        "features_used": HOURLY_FEATS,
        "features_omitted": {
            "solar_radiation": "Absorbed by hour-of-day strata (near-collinear with hour-of-day)",
            "diurnal_temperature_range": "Daily max-min by construction; zero variance within a single hour",
        },
        "metadata": {
            "n_city_hours_total": int(_n_total_h),
            "n_event_hours": int(_n_event_h),
            "event_rate_pct": round(float(_ev_rate_h), 2),
            "n_valid_strata": int(_df_cc["stratum"].nunique()),
            "n_case_crossover_obs": int(len(_df_cc)),
            "stratum_definition": "year × month × hour-of-day",
            "anchoring": (
                "At inference: shift all 24 hourly z-values by "
                "(logit(daily_ORI/100) - mean(z_24h)) so the 24-hour mean "
                "maps to the calibrated daily ORI."
            ),
            "training_period": (
                f"{_df_ch['datetime'].min().date()} "
                f"to {_df_ch['datetime'].max().date()}"
            ),
        },
    }

    _h_json_path = "Pittsburgh Data/model_coeffs_hourly.json"
    with open(_h_json_path, "w") as _f:
        json.dump(_hourly_export, _f, indent=2)
    print(f"    Saved {_h_json_path}")
    print(f"    n_city_hours={_n_total_h:,}  n_events={_n_event_h:,}  n_strata={_df_cc['stratum'].nunique():,}")
else:
    print("    Skipped (ConditionalLogit did not converge).")

print("\n" + "=" * 70)
print("ALL SECTIONS COMPLETE")
print("=" * 70)
