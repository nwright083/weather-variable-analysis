"""
Dual Model Proximity Analysis — Louisville, KY
===============================================
Compares weather-only (Model A) vs proximity-enhanced (Model B) Poisson GLM + Logit/ORI models.
New features: emission-source distance decay + continuous wind-alignment factor (0-1).

Outputs:
  - Louisville Data/dual_model_*.png  (multiple figures)
  - Louisville Data/model_coeffs_louisville.json
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import os
import json
import math
import warnings
import subprocess
import sys

import pandas as pd
import numpy as np
import seaborn as sns

warnings.filterwarnings('ignore')
sns.set_theme(style="whitegrid")

# ── install optional packages silently ──────────────────────────────────────
def _ensure(pkg, import_name=None):
    import_name = import_name or pkg
    try:
        __import__(import_name)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

_ensure('holidays')
_ensure('statsmodels')
_ensure('scikit-learn', 'sklearn')
_ensure('nbformat')

import holidays
import statsmodels.api as sm
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, roc_curve

# ── plot-saver helper ────────────────────────────────────────────────────────
PLOT_DIR = 'Louisville Data'
_fig_counter = [0]

def save_show(title_slug):
    _fig_counter[0] += 1
    path = os.path.join(PLOT_DIR, f'dual_model_{_fig_counter[0]:02d}_{title_slug}.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'  Saved → {path}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: Setup & Data Loading
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 1 — Data Loading & Feature Engineering')
print('='*70)

CSV_PATH = os.path.join('Louisville Data', 'open-meteo-smell-merged.csv')
if not os.path.exists(CSV_PATH):
    raise FileNotFoundError(f'Cannot find {CSV_PATH}')

print(f'Reading {CSV_PATH} …')
USECOLS = [
    'time', 'location_id', 'latitude', 'longitude', 'zipcode',
    'temperature_2m (°F)', 'relative_humidity_2m (%)', 'wind_speed_10m (mp/h)',
    'wind_direction_10m (°)', 'rain (inch)', 'dew_point_2m (°F)',
    'vapour_pressure_deficit (kPa)', 'surface_pressure (hPa)',
    'shortwave_radiation (W/m²)', 'sunshine_duration (s)',
    'boundary_layer_height (ft)', 'smell_report_count', 'smell_value_average',
    'smell_value_max',
]

DTYPE_MAP = {
    'zipcode': 'int32',
    'smell_report_count': 'float32',
    'smell_value_average': 'float32',
    'temperature_2m (°F)': 'float32',
    'relative_humidity_2m (%)': 'float32',
    'wind_speed_10m (mp/h)': 'float32',
    'wind_direction_10m (°)': 'float32',
    'rain (inch)': 'float32',
    'vapour_pressure_deficit (kPa)': 'float32',
    'surface_pressure (hPa)': 'float32',
    'shortwave_radiation (W/m²)': 'float32',
    'sunshine_duration (s)': 'float32',
    'boundary_layer_height (ft)': 'float32',
    'latitude': 'float32',
    'longitude': 'float32',
}

df_raw = pd.read_csv(CSV_PATH, usecols=USECOLS, dtype=DTYPE_MAP, low_memory=False)
print(f'  Loaded {len(df_raw):,} rows, {df_raw.shape[1]} columns')

# ── column mapping ────────────────────────────────────────────────────────
RENAME = {
    'time': 'datetime',
    'smell_report_count': 'complaints',
    'temperature_2m (°F)': 'temperature',
    'relative_humidity_2m (%)': 'relative_humidity',
    'wind_speed_10m (mp/h)': 'wind_speed',
    'wind_direction_10m (°)': 'wind_direction',
    'rain (inch)': 'precipitation',
    'dew_point_2m (°F)': 'dew_point',
    'vapour_pressure_deficit (kPa)': 'vapor_pressure',
    'surface_pressure (hPa)': 'atmospheric_pressure',
    'shortwave_radiation (W/m²)': 'solar_radiation',
    'sunshine_duration (s)': 'sunshine_duration',
    'boundary_layer_height (ft)': 'boundary_layer_height',
}
df = df_raw.rename(columns=RENAME).copy()
df['datetime'] = pd.to_datetime(df['datetime'])
df['complaints'] = df['complaints'].fillna(0).astype('float32')
df['smell_value_average'] = df['smell_value_average'].fillna(0).astype('float32')

# ── zip centroids ─────────────────────────────────────────────────────────
zip_centroids_df = df.groupby('zipcode')[['latitude', 'longitude']].mean()
zip_centroids = {
    z: {'lat': float(row['latitude']), 'lon': float(row['longitude'])}
    for z, row in zip_centroids_df.iterrows()
}
print(f'  Found {len(zip_centroids)} unique zip codes')

# ── circular wind-direction mean ──────────────────────────────────────────
def circular_wind_mean(series):
    rads = np.radians(series.dropna().astype(float))
    if len(rads) == 0:
        return np.nan
    u = np.mean(np.sin(rads))
    v = np.mean(np.cos(rads))
    return (np.degrees(np.arctan2(u, v)) + 360) % 360

# ── daily zip-level aggregation (named-agg → flat columns, no ambiguity) ──
df['date'] = df['datetime'].dt.date

print('  Aggregating to daily zip-level panel …')
daily_zip = df.groupby(['zipcode', 'date']).agg(
    complaints=('complaints', 'sum'),
    temperature=('temperature', 'mean'),
    temp_min=('temperature', 'min'),
    temp_max=('temperature', 'max'),
    precipitation=('precipitation', 'sum'),
    wind_speed=('wind_speed', 'mean'),
    wind_direction=('wind_direction', circular_wind_mean),
    relative_humidity=('relative_humidity', 'mean'),
    vapor_pressure=('vapor_pressure', 'mean'),
    atmospheric_pressure=('atmospheric_pressure', 'mean'),
    solar_radiation=('solar_radiation', 'mean'),
    boundary_layer_height=('boundary_layer_height', 'mean'),
    smell_value_average=('smell_value_average', 'mean'),
).reset_index()
daily_zip['date'] = pd.to_datetime(daily_zip['date'])

print(f'  Daily zip panel: {len(daily_zip):,} rows')

# ── derived features ──────────────────────────────────────────────────────
daily_zip['diurnal_temperature_range'] = daily_zip['temp_max'] - daily_zip['temp_min']
daily_zip['temperature_squared'] = daily_zip['temperature'] ** 2

threshold = (daily_zip['complaints'] * daily_zip['smell_value_average']).mean()
daily_zip['is_odor_event'] = (
    (daily_zip['complaints'] * daily_zip['smell_value_average']) > threshold
).astype(int)

# Day-of-week dummies (Monday=0 = reference; keep Tue–Sun)
# pd.get_dummies with prefix='dow' produces columns named 'dow_0', 'dow_1', ...'dow_6'
dow = pd.get_dummies(daily_zip['date'].dt.dayofweek, prefix='dow')
dow_map = {
    'dow_1': 'dow_tue',
    'dow_2': 'dow_wed',
    'dow_3': 'dow_thu',
    'dow_4': 'dow_fri',
    'dow_5': 'dow_sat',
    'dow_6': 'dow_sun',
}
for src_col, dst_col in dow_map.items():
    if src_col in dow.columns:
        daily_zip[dst_col] = dow[src_col].astype(int).values
    else:
        daily_zip[dst_col] = 0

# Holidays
us_holidays = holidays.US()
daily_zip['is_holiday'] = daily_zip['date'].apply(lambda d: int(d in us_holidays))

print(f'  Odor events: {daily_zip["is_odor_event"].sum():,} / {len(daily_zip):,}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: Proximity Feature Engineering
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 2 — Proximity Feature Engineering')
print('='*70)

EMISSION_SOURCES = {
    'Rubbertown': (38.2195, -85.8450),
    'JBS_Swift_Butchertown': (38.2588, -85.7275),
}


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def bearing(src_lat, src_lon, dst_lat, dst_lon):
    dy = dst_lat - src_lat
    dx = (dst_lon - src_lon) * math.cos(math.radians(src_lat))
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def continuous_wind_alignment(wind_from_deg, bearing_deg):
    """Returns 0-1: 1 = wind blows directly from source toward receiver."""
    wind_toward = (wind_from_deg + 180) % 360
    angle_diff = math.radians(wind_toward - bearing_deg)
    return (1 + math.cos(angle_diff)) / 2


# Pre-compute per-zip static values (distance & bearing don't depend on date/time)
print('  Computing per-zip distances and bearings …')
zip_static = {}
for z, centroid in zip_centroids.items():
    zip_static[z] = {}
    for src_name, (src_lat, src_lon) in EMISSION_SOURCES.items():
        d = haversine_miles(src_lat, src_lon, centroid['lat'], centroid['lon'])
        b = bearing(src_lat, src_lon, centroid['lat'], centroid['lon'])
        zip_static[z][f'dist_{src_name}'] = d
        zip_static[z][f'exp02_{src_name}'] = math.exp(-0.02 * d)
        zip_static[z][f'bearing_{src_name}'] = b

# Map static features onto daily_zip
for src_name in EMISSION_SOURCES:
    daily_zip[f'dist_{src_name}'] = daily_zip['zipcode'].map(
        {z: v[f'dist_{src_name}'] for z, v in zip_static.items()})
    daily_zip[f'exp02_{src_name}'] = daily_zip['zipcode'].map(
        {z: v[f'exp02_{src_name}'] for z, v in zip_static.items()})
    daily_zip[f'bearing_{src_name}'] = daily_zip['zipcode'].map(
        {z: v[f'bearing_{src_name}'] for z, v in zip_static.items()})

print('  Computing continuous wind alignment …')

def _wind_align_row(row, src_name):
    wd = row['wind_direction']
    b = row[f'bearing_{src_name}']
    if pd.isna(wd) or pd.isna(b):
        return 0.5
    return continuous_wind_alignment(float(wd), float(b))

for src_name in EMISSION_SOURCES:
    daily_zip[f'wind_align_{src_name}'] = daily_zip.apply(
        lambda r: _wind_align_row(r, src_name), axis=1)

# Aggregate multi-source metrics
exp_cols  = [f'exp02_{s}' for s in EMISSION_SOURCES]
align_cols = [f'wind_align_{s}' for s in EMISSION_SOURCES]

daily_zip['multi_source_exposure'] = daily_zip[exp_cols].sum(axis=1)
exp_sum = daily_zip[exp_cols].sum(axis=1).replace(0, np.nan)
daily_zip['wind_align_weighted'] = (
    sum(daily_zip[f'exp02_{s}'] * daily_zip[f'wind_align_{s}'] for s in EMISSION_SOURCES)
    / exp_sum
)
daily_zip['wind_align_weighted'].fillna(0.5, inplace=True)

# Nearest-source distance (convenience column for plotting)
dist_cols = [f'dist_{s}' for s in EMISSION_SOURCES]
daily_zip['dist_nearest'] = daily_zip[dist_cols].min(axis=1)

print(f'  multi_source_exposure range: '
      f'{daily_zip["multi_source_exposure"].min():.3f} – '
      f'{daily_zip["multi_source_exposure"].max():.3f}')
print(f'  wind_align_weighted range:   '
      f'{daily_zip["wind_align_weighted"].min():.3f} – '
      f'{daily_zip["wind_align_weighted"].max():.3f}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: Binned Distribution Plots
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 3 — Binned Distribution Plots')
print('='*70)

plot_features = {
    'dist_nearest':          'Distance to Nearest Source (miles)',
    'multi_source_exposure': 'Multi-Source Exposure (decay sum)',
    'wind_align_weighted':   'Wind Alignment Factor (0–1)',
}

for feat, label in plot_features.items():
    try:
        temp = daily_zip[[feat, 'complaints']].dropna()
        temp['bin'] = pd.qcut(temp[feat], q=8, duplicates='drop')
        grp = temp.groupby('bin', observed=True)['complaints']
        means = grp.mean()
        sems  = grp.sem()

        fig, ax = plt.subplots(figsize=(9, 5))
        x = range(len(means))
        ax.bar(x, means.values, yerr=sems.values, capsize=4, color='steelblue',
               alpha=0.8, error_kw={'elinewidth': 1.2})
        ax.set_xticks(list(x))
        ax.set_xticklabels([str(b) for b in means.index], rotation=30, ha='right', fontsize=8)
        ax.set_xlabel(label)
        ax.set_ylabel('Mean Daily Complaints')
        ax.set_title(f'Mean Daily Complaints by {label} Bin')
        plt.tight_layout()
        save_show(f'bin_{feat}')
    except Exception as e:
        print(f'  Warning: could not plot {feat}: {e}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: Feature Importance Screening (Statistical Models)
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 4 — Feature Importance Screening')
print('='*70)

WEATHER_VARS = [
    'temperature', 'temperature_squared', 'solar_radiation', 'relative_humidity',
    'wind_speed', 'precipitation', 'diurnal_temperature_range',
    'boundary_layer_height', 'atmospheric_pressure',
    'dow_tue', 'dow_wed', 'dow_thu', 'dow_fri', 'dow_sat', 'dow_sun', 'is_holiday',
]

MODEL_SPECS = {
    'Model 1 — Weather Only':           WEATHER_VARS,
    'Model 2 — +Proximity':             WEATHER_VARS + ['multi_source_exposure'],
    'Model 3 — +Wind Alignment':        WEATHER_VARS + ['wind_align_weighted'],
    'Model 4 — +Both (Prox-Enhanced)':  WEATHER_VARS + ['multi_source_exposure', 'wind_align_weighted'],
}

# ── prepare modelling frame ───────────────────────────────────────────────
all_needed = list(set(WEATHER_VARS + ['complaints', 'is_odor_event',
                                      'multi_source_exposure', 'wind_align_weighted']))
model_df = daily_zip[all_needed].dropna()
print(f'  Modelling frame: {len(model_df):,} rows after dropna')

y_count  = model_df['complaints'].astype(float)
y_binary = model_df['is_odor_event'].astype(float)

results = {}   # {spec_name: {'poisson': result, 'logit': result}}

for spec_name, features in MODEL_SPECS.items():
    print(f'\n  Fitting: {spec_name}')
    X = sm.add_constant(model_df[features].astype(float))

    # Poisson GLM
    try:
        poisson_res = sm.GLM(y_count, X, family=sm.families.Poisson()).fit(disp=False)
        print(f'    Poisson  AIC={poisson_res.aic:.1f}  Pseudo-R²={1 - poisson_res.deviance/poisson_res.null_deviance:.4f}')
    except Exception as e:
        print(f'    Poisson failed: {e}')
        poisson_res = None

    # Logit
    try:
        logit_res = sm.Logit(y_binary, X).fit(disp=0, maxiter=200)
        llf = logit_res.llf
        llnull = logit_res.llnull
        pr2 = 1 - llf / llnull
        print(f'    Logit    AIC={logit_res.aic:.1f}  Pseudo-R²={pr2:.4f}')
    except Exception as e:
        print(f'    Logit failed: {e}')
        logit_res = None

    results[spec_name] = {'poisson': poisson_res, 'logit': logit_res}

# ── comparison table ──────────────────────────────────────────────────────
print('\n  ── Model Comparison Table ──')
print(f'  {"Model":<42} {"Type":<10} {"Pseudo-R²":>10} {"Log-Lik":>12} {"AIC":>10}')
print('  ' + '-'*86)
for spec_name, res_dict in results.items():
    for model_type, res in res_dict.items():
        if res is None:
            continue
        if model_type == 'poisson':
            pr2 = 1 - res.deviance / res.null_deviance
            llf = res.llf
        else:
            llf = res.llf
            pr2 = 1 - llf / res.llnull
        print(f'  {spec_name:<42} {model_type:<10} {pr2:>10.4f} {llf:>12.1f} {res.aic:>10.1f}')

# ── significance of new features in Model 4 ──────────────────────────────
m4_logit = results['Model 4 — +Both (Prox-Enhanced)']['logit']
if m4_logit is not None:
    print('\n  Model 4 Logit — new feature coefficients:')
    for feat in ['multi_source_exposure', 'wind_align_weighted']:
        if feat in m4_logit.params:
            coef = m4_logit.params[feat]
            pval = m4_logit.pvalues[feat]
            sig  = '***' if pval < 0.001 else ('**' if pval < 0.01 else ('*' if pval < 0.05 else ''))
            print(f'    {feat:<30}  coef={coef:+.4f}  p={pval:.4f} {sig}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: Dual-Model Comparison & Graph Suite
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 5 — Dual-Model Comparison & Graphs')
print('='*70)

logit_wa = results['Model 1 — Weather Only']['logit']          # weather-only
logit_pe = results['Model 4 — +Both (Prox-Enhanced)']['logit'] # proximity-enhanced

if logit_wa is None or logit_pe is None:
    print('  WARNING: one or both logit models failed — skipping graph suite.')
else:
    X_wa = sm.add_constant(model_df[WEATHER_VARS].astype(float))
    X_pe = sm.add_constant(model_df[WEATHER_VARS + ['multi_source_exposure', 'wind_align_weighted']].astype(float))

    # ── 5A: Metrics comparison table ─────────────────────────────────────
    def pseudo_r2(res):
        return 1 - res.llf / res.llnull

    # 5-fold CV AUC
    def cv_auc(X_df, y_ser, n_splits=5):
        X_np = X_df.values
        y_np = y_ser.values
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        aucs = []
        for train_idx, test_idx in skf.split(X_np, y_np):
            try:
                m = sm.Logit(y_np[train_idx], X_np[train_idx]).fit(disp=0, maxiter=200)
                probs = m.predict(X_np[test_idx])
                aucs.append(roc_auc_score(y_np[test_idx], probs))
            except Exception:
                pass
        return float(np.mean(aucs)) if aucs else float('nan')

    print('  Running 5-fold CV AUC (this may take a moment) …')
    auc_wa = cv_auc(X_wa, y_binary)
    auc_pe = cv_auc(X_pe, y_binary)

    print('\n  ── Dual-Model Metrics ──')
    print(f'  {"Metric":<25} {"Weather-Only":>15} {"Prox-Enhanced":>15}')
    print('  ' + '-'*57)
    print(f'  {"Pseudo-R²":<25} {pseudo_r2(logit_wa):>15.4f} {pseudo_r2(logit_pe):>15.4f}')
    print(f'  {"5-fold CV AUC":<25} {auc_wa:>15.4f} {auc_pe:>15.4f}')
    print(f'  {"AIC":<25} {logit_wa.aic:>15.1f} {logit_pe.aic:>15.1f}')
    delta_aic = logit_wa.aic - logit_pe.aic
    print(f'  {"ΔAIC (WO − PE)":<25} {delta_aic:>15.2f}  {"← PE better" if delta_aic > 0 else "← WO better"}')

    # ── 5B: Coefficient comparison plot ──────────────────────────────────
    common_vars = [v for v in WEATHER_VARS if v in logit_wa.params and v in logit_pe.params]

    fig, ax = plt.subplots(figsize=(10, 7))
    y_pos   = np.arange(len(common_vars))
    coef_wa = [logit_wa.params[v] for v in common_vars]
    coef_pe = [logit_pe.params[v] for v in common_vars]
    bar_h   = 0.35

    ax.barh(y_pos + bar_h/2, coef_wa, bar_h, label='Weather-Only', color='steelblue', alpha=0.8)
    ax.barh(y_pos - bar_h/2, coef_pe, bar_h, label='Prox-Enhanced', color='tomato', alpha=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(common_vars, fontsize=9)
    ax.axvline(0, color='black', linewidth=0.8, linestyle='--')
    ax.set_xlabel('Logit Coefficient')
    ax.set_title('Logit Coefficients — Weather-Only vs Proximity-Enhanced')
    ax.legend()
    plt.tight_layout()
    save_show('coef_comparison')

    # ── 5C: ORI probability histogram ────────────────────────────────────
    pred_wa = logit_wa.predict(X_wa)
    pred_pe = logit_pe.predict(X_pe)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(pred_wa, bins=40, alpha=0.5, label='Weather-Only', color='steelblue', density=True)
    ax.hist(pred_pe, bins=40, alpha=0.5, label='Prox-Enhanced', color='tomato', density=True)
    ax.set_xlabel('Predicted ORI Probability')
    ax.set_ylabel('Density')
    ax.set_title('Distribution of Predicted ORI Probabilities')
    ax.legend()
    plt.tight_layout()
    save_show('ori_histogram')

    # ── 5D: ROC curves ───────────────────────────────────────────────────
    fpr_wa, tpr_wa, _ = roc_curve(y_binary, pred_wa)
    fpr_pe, tpr_pe, _ = roc_curve(y_binary, pred_pe)
    auc_full_wa = roc_auc_score(y_binary, pred_wa)
    auc_full_pe = roc_auc_score(y_binary, pred_pe)

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot(fpr_wa, tpr_wa, lw=2, color='steelblue',
            label=f'Weather-Only  AUC={auc_full_wa:.3f}')
    ax.plot(fpr_pe, tpr_pe, lw=2, color='tomato',
            label=f'Prox-Enhanced AUC={auc_full_pe:.3f}')
    ax.plot([0, 1], [0, 1], 'k--', lw=0.8)
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.set_title('ROC Curves — Weather-Only vs Proximity-Enhanced Logit')
    ax.legend(loc='lower right')
    plt.tight_layout()
    save_show('roc_curves')

    # ── 5E: Full coefficient table for proximity features ─────────────────
    print('\n  Model 4 Full Logit Summary (proximity features):')
    for feat in ['multi_source_exposure', 'wind_align_weighted']:
        if feat in logit_pe.params.index:
            coef = logit_pe.params[feat]
            se   = logit_pe.bse[feat]
            ci   = logit_pe.conf_int().loc[feat]
            pval = logit_pe.pvalues[feat]
            print(f'    {feat:<30}  coef={coef:+.4f}  SE={se:.4f}  '
                  f'CI=[{ci[0]:+.4f}, {ci[1]:+.4f}]  p={pval:.4f}')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: Export Coefficients
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 6 — Export Coefficients to JSON')
print('='*70)

def _safe_float(val):
    try:
        return float(val)
    except Exception:
        return None

if logit_wa is not None and logit_pe is not None:
    def params_to_dict(res, keys):
        return {k: _safe_float(res.params.get(k, 0.0)) for k in keys}

    wa_keys = ['const'] + WEATHER_VARS
    pe_keys = ['const'] + WEATHER_VARS + ['multi_source_exposure', 'wind_align_weighted']

    coeffs = {
        'city': 'Louisville',
        'weather_only': params_to_dict(logit_wa, wa_keys),
        'proximity_enhanced': params_to_dict(logit_pe, pe_keys),
        'model_metrics': {
            'weather_only_pseudo_r2':     _safe_float(pseudo_r2(logit_wa)),
            'proximity_enhanced_pseudo_r2': _safe_float(pseudo_r2(logit_pe)),
            'weather_only_aic':            _safe_float(logit_wa.aic),
            'proximity_enhanced_aic':      _safe_float(logit_pe.aic),
            'delta_aic':                   _safe_float(logit_wa.aic - logit_pe.aic),
            'weather_only_cv_auc':         _safe_float(auc_wa),
            'proximity_enhanced_cv_auc':   _safe_float(auc_pe),
            'roc_auc_full_wa':             _safe_float(auc_full_wa),
            'roc_auc_full_pe':             _safe_float(auc_full_pe),
        },
        'proximity_feature_significance': {}
    }

    for feat in ['multi_source_exposure', 'wind_align_weighted']:
        if feat in logit_pe.params.index:
            coeffs['proximity_feature_significance'][feat] = {
                'coef':  _safe_float(logit_pe.params[feat]),
                'pvalue': _safe_float(logit_pe.pvalues[feat]),
                'significant_p10': bool(logit_pe.pvalues[feat] < 0.10),
            }

    JSON_PATH = os.path.join('Louisville Data', 'model_coeffs_louisville.json')
    with open(JSON_PATH, 'w') as f:
        json.dump(coeffs, f, indent=2)
    print(f'  Saved → {JSON_PATH}')
else:
    print('  WARNING: Logit models unavailable — skipping JSON export.')

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: Create Jupyter Notebook
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('SECTION 7 — Building Jupyter Notebook')
print('='*70)

import nbformat as nbf

SCRIPT_PATH = os.path.join('Louisville Data', 'Dual_Model_Proximity_Analysis.py')
with open(SCRIPT_PATH, 'r') as f:
    script_lines = f.readlines()

# ── split into sections by comment markers ────────────────────────────────
def split_into_cells(lines):
    """
    Returns list of (cell_type, text) tuples.
    '# ═══' lines start a new markdown cell with the section title.
    Everything else accumulates into code cells.
    """
    cells = []
    current_code = []

    i = 0
    while i < len(lines):
        line = lines[i]
        # Section header block: '# ═══…' followed by '# SECTION N — …' + closing '# ═══…'
        if line.strip().startswith('# ═══'):
            # flush pending code
            if any(l.strip() for l in current_code):
                cells.append(('code', ''.join(current_code)))
            current_code = []
            # gather section title
            header_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('# ═══'):
                header_lines.append(lines[i].lstrip('# ').rstrip())
                i += 1
            i += 1  # skip closing ═══ line
            title = ' '.join(h for h in header_lines if h).strip()
            cells.append(('markdown', f'## {title}'))
        else:
            current_code.append(line)
            i += 1

    if any(l.strip() for l in current_code):
        cells.append(('code', ''.join(current_code)))

    return cells

cells_raw = split_into_cells(script_lines)

nb = nbf.v4.new_notebook()
nb_cells = []

# Title cell
nb_cells.append(nbf.v4.new_markdown_cell(
    '# Dual Model Proximity Analysis — Louisville, KY\n\n'
    'Compares **weather-only** (Model A) vs **proximity-enhanced** (Model B) '
    'Poisson GLM + Logit/ORI models.\n\n'
    'New features engineered:\n'
    '- **Emission-source distance decay** (`multi_source_exposure`)\n'
    '- **Continuous wind-alignment factor** (`wind_align_weighted`, range 0–1)\n\n'
    'Sources: Rubbertown (chemical corridor) and JBS Swift Butchertown (meat processing).'
))

for cell_type, content in cells_raw:
    if cell_type == 'markdown':
        nb_cells.append(nbf.v4.new_markdown_cell(content))
    else:
        # Skip empty or near-empty code cells
        if content.strip():
            nb_cells.append(nbf.v4.new_code_cell(content))

nb.cells = nb_cells

IPYNB_PATH = os.path.join('Louisville Data', 'Dual_Model_Proximity_Analysis.ipynb')
with open(IPYNB_PATH, 'w') as f:
    nbf.write(nb, f)

print(f'  Notebook written → {IPYNB_PATH} ({len(nb_cells)} cells)')

# ═══════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('COMPLETE — Dual Model Proximity Analysis')
print('='*70)
print(f'  Script:   Louisville Data/Dual_Model_Proximity_Analysis.py')
print(f'  Notebook: Louisville Data/Dual_Model_Proximity_Analysis.ipynb')
print(f'  JSON:     Louisville Data/model_coeffs_louisville.json')
print(f'  Plots:    Louisville Data/dual_model_*.png')
print('='*70)
