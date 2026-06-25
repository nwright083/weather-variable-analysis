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

print("\n" + "=" * 70)
print("ALL SECTIONS COMPLETE")
print("=" * 70)
