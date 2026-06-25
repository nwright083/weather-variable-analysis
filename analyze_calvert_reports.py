"""Calvert City report → weather/spatial coefficient analyzer.

Run this periodically (e.g. once you have a few dozen real odor reports) to test
whether ANY of the deployed model's coefficients should be adjusted for Calvert
City specifically — including the weather variables, the wind-alignment strength,
and the distance-decay rate. Calvert's odor sources are chemical plants, which may
behave differently from Pittsburgh's coke/steel works (the model's training city);
this script lets the local data tell you where they diverge.

──────────────────────────────────────────────────────────────────────────────
WHAT IT DOES
  1. Loads odor reports from:
       • the tester database (calvert_tester_logs.db, `reports` table), and/or
       • a Google-Form responses CSV (local file or a "Publish to web" CSV URL).
  2. For every report it fetches that day's (and the prior day's) weather from the
     Open-Meteo ERA5 archive at the report's coordinates, and computes the exact
     model features (temp, RH, wind speed, wind direction → wind_alignment,
     boundary-layer height, pressure, precip, DTR, distance-from-source, exposure).
  3. Picks an analysis mode automatically:
       • CASE-CONTROL   — if reports carry an odor_detected yes/no flag (tester db)
       • USE-vs-AVAILABILITY — for presence-only data (public form): each report
         day is a "used" day; a background sample of days at the same location are
         "available" controls. This yields logit coefficients on the same scale as
         the model, so they're directly comparable.
  4. Runs a univariate screen + (if enough data) a multivariate logistic regression,
     then compares every estimated coefficient against the DEPLOYED coefficients in
     odor_forecast_core.COEFFS_PITTSBURGH_PROXIMITY, flagging sign flips and large
     magnitude divergences (with p-values and a blunt sample-size caveat).
  5. Writes a CSV + JSON summary and prints a plain-language report.
  6. GENERATES a candidate Calvert-fitted model (severity-weighted logistic fit),
     cross-validates it against the deployed model, and — only if it clears the
     quality gates (enough reports, AUC floor, beats deployed) — asks at the
     terminal whether to install it. If you accept, it writes
     calvert_fitted_model.json, which odor_forecast_core auto-loads and
     generate_site exposes as a new "Calvert City (Data-Fitted)" dashboard mode
     (and makes it the default). Re-run generate_site.py to rebuild, then commit
     the JSON. Use --yes to skip the prompt, --no to analyze without installing.

──────────────────────────────────────────────────────────────────────────────
USAGE
  .venv/bin/python analyze_calvert_reports.py                 # tester db only
  .venv/bin/python analyze_calvert_reports.py --csv responses.csv
  .venv/bin/python analyze_calvert_reports.py --sheet-url "https://docs.google.com/.../pub?output=csv"
  .venv/bin/python analyze_calvert_reports.py --background-days 365 --min-reports 30

  To get the --sheet-url: in the linked Google Sheet → File → Share → Publish to
  web → choose the responses sheet → CSV → copy the URL.

Nothing here touches the deployed model. It only *recommends* changes for you to
review; applying them is a deliberate manual edit to odor_forecast_core.py.
"""
import os
import sys
import json
import time
import argparse
import sqlite3
import datetime as dt

import numpy as np
import pandas as pd
import requests

import odor_forecast_core as core

ROOT = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE_PATH = os.path.join(ROOT, "scratch", "calvert_weather_cache.json")

# Model features we test, in the order the deployed coefficients use them.
WEATHER_FEATURES = [
    "temperature", "temperature_squared", "solar_radiation", "relative_humidity",
    "wind_speed", "precipitation", "diurnal_temperature_range",
    "boundary_layer_height", "atmospheric_pressure",
]
SPATIAL_FEATURES = ["distance_from_source", "multi_source_exposure", "wind_alignment"]
LAG_FEATURES = ["precipitation_lag1"]  # the residents' "after rain" hypothesis
ALL_FEATURES = WEATHER_FEATURES + SPATIAL_FEATURES + LAG_FEATURES


# ── Report loading ─────────────────────────────────────────────────────────────

def load_reports_from_db(db_path):
    if not os.path.exists(db_path):
        return pd.DataFrame()
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT date_reported AS ts, latitude, longitude, "
            "odor_detected, severity FROM reports", con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()
    df["source"] = "tester_db"
    return df


def _find_col(cols, *needles):
    for c in cols:
        lc = c.lower()
        if all(n in lc for n in needles):
            return c
    return None


def load_reports_from_csv(text_or_path, is_url=False):
    df = pd.read_csv(text_or_path)
    cols = list(df.columns)
    ts = _find_col(cols, "timestamp") or _find_col(cols, "time") or _find_col(cols, "date")
    lat = _find_col(cols, "lat")
    lon = _find_col(cols, "lon") or _find_col(cols, "lng") or _find_col(cols, "long")
    det = _find_col(cols, "odor", "detect") or _find_col(cols, "detect") or _find_col(cols, "smell", "detect")
    sev = _find_col(cols, "sever") or _find_col(cols, "intens") or _find_col(cols, "strength")
    out = pd.DataFrame({
        "ts": df[ts] if ts else pd.NaT,
        "latitude": pd.to_numeric(df[lat], errors="coerce") if lat else np.nan,
        "longitude": pd.to_numeric(df[lon], errors="coerce") if lon else np.nan,
        "odor_detected": df[det] if det else "Yes",  # public form = presence only
        "severity": pd.to_numeric(df[sev], errors="coerce") if sev else np.nan,
    })
    out["source"] = "form_url" if is_url else "form_csv"
    return out


def normalize_reports(df):
    if df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["ts"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    # Default missing coords to the industrial source neighborhood (best guess).
    df["latitude"] = df["latitude"].fillna(core.IND_LAT)
    df["longitude"] = df["longitude"].fillna(core.IND_LON)

    def to_bool(v):
        if pd.isna(v):
            return np.nan
        s = str(v).strip().lower()
        if s in ("yes", "y", "true", "1", "detected"):
            return 1
        if s in ("no", "n", "false", "0", "none", "not detected"):
            return 0
        return np.nan
    df["odor_detected"] = df["odor_detected"].apply(to_bool)
    return df.dropna(subset=["date"])


# ── Weather fetch (ERA5 archive, hourly → daily, mirrors odor_forecast_core) ────

def _load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as fh:
        json.dump(cache, fh)


def _aggregate_hourly_to_daily(hourly):
    """Mirror the daily aggregation used in odor_forecast_core.fetch_forecasts so
    the analysis features match what the deployed model consumes."""
    df = pd.DataFrame(hourly)
    if df.empty or "time" not in df:
        return pd.DataFrame()
    df["time"] = pd.to_datetime(df["time"])
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "boundary_layer_height" in df:
        df["blh_ft"] = pd.to_numeric(df["boundary_layer_height"], errors="coerce") * 3.28084
    else:
        df["blh_ft"] = 1500.0
    for c in ["temperature_2m", "relative_humidity_2m", "surface_pressure",
              "wind_speed_10m", "wind_direction_10m", "rain", "shortwave_radiation"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # vector-mean wind direction (avoids 0/360 wrap error)
    df["wind_u"] = df["wind_speed_10m"] * np.sin(np.radians(df["wind_direction_10m"]))
    df["wind_v"] = df["wind_speed_10m"] * np.cos(np.radians(df["wind_direction_10m"]))
    g = df.groupby("date").agg(
        temperature=("temperature_2m", "mean"),
        temp_min=("temperature_2m", "min"),
        temp_max=("temperature_2m", "max"),
        precipitation=("rain", "sum"),
        wind_speed=("wind_speed_10m", "mean"),
        wind_u=("wind_u", "mean"),
        wind_v=("wind_v", "mean"),
        relative_humidity=("relative_humidity_2m", "mean"),
        atmospheric_pressure=("surface_pressure", "mean"),
        solar_radiation=("shortwave_radiation", "mean"),
        boundary_layer_height=("blh_ft", "mean"),
    ).reset_index()
    g["wind_direction"] = np.degrees(np.arctan2(g["wind_u"], g["wind_v"])) % 360
    g["diurnal_temperature_range"] = g["temp_max"] - g["temp_min"]
    g["temperature_squared"] = g["temperature"] ** 2
    return g.drop(columns=["wind_u", "wind_v"])


def fetch_daily_weather(lat, lon, start_date, end_date, cache):
    key = f"{lat:.4f},{lon:.4f},{start_date},{end_date}"
    if key in cache:
        return pd.DataFrame(cache[key])
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": ("temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,"
                   "wind_direction_10m,rain,shortwave_radiation,boundary_layer_height"),
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "precipitation_unit": "inch", "timezone": "America/Chicago",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=30)
    r.raise_for_status()
    daily = _aggregate_hourly_to_daily(r.json().get("hourly", {}))
    cache[key] = daily.to_dict(orient="list")
    time.sleep(0.4)  # be polite to the free API
    return daily


def add_spatial_features(daily, lat, lon):
    daily = daily.copy()
    bearing = core.calculate_bearing(lat, lon)
    dist = core.calculate_distance(lat, lon)
    daily["distance_from_source"] = dist
    daily["multi_source_exposure"] = np.exp(-0.02 * dist)
    daily["wind_alignment"] = daily["wind_direction"].apply(
        lambda wd: core.compute_continuous_wind_alignment(wd, bearing))
    return daily


# ── Build modeling table ───────────────────────────────────────────────────────

def build_used_available(reports, background_days, cache):
    """Returns a long DataFrame with feature columns and a `used` (1/0) label.

    Case-control: if reports have odor_detected, used = that flag (each report day).
    Use-availability: presence-only reports → used=1 on report days; background
    days at the same location → used=0 controls.
    """
    rows = []
    has_labels = reports["odor_detected"].notna().any()
    case_control = has_labels and (reports["odor_detected"].nunique() >= 2)

    # Unique locations (rounded) so we batch archive fetches.
    reports = reports.copy()
    reports["loc_key"] = (reports["latitude"].round(3).astype(str) + "," +
                          reports["longitude"].round(3).astype(str))

    for loc_key, grp in reports.groupby("loc_key"):
        lat, lon = map(float, loc_key.split(","))
        report_dates = pd.to_datetime(grp["date"])
        # Date span: cover reports plus background window and one prior day for lags.
        end = report_dates.max()
        if case_control:
            start = report_dates.min() - pd.Timedelta(days=2)
        else:
            start = report_dates.min() - pd.Timedelta(days=int(background_days))
        start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        try:
            daily = fetch_daily_weather(lat, lon, start_s, end_s, cache)
        except Exception as e:
            print(f"  ! weather fetch failed for {loc_key}: {e}")
            continue
        if daily.empty:
            continue
        daily = add_spatial_features(daily, lat, lon).sort_values("date").reset_index(drop=True)
        daily["precipitation_lag1"] = daily["precipitation"].shift(1)

        report_day_set = set(grp["date"])
        sev_by_date = grp.groupby("date")["severity"].max().to_dict()
        if case_control:
            label_by_date = dict(zip(grp["date"], grp["odor_detected"]))
            sub = daily[daily["date"].isin(report_day_set)].copy()
            sub["used"] = sub["date"].map(label_by_date)
        else:
            daily["used"] = daily["date"].isin(report_day_set).astype(int)
            sub = daily
        sub["severity"] = sub["date"].map(sev_by_date)  # NaN on control days
        rows.append(sub)

    if not rows:
        return pd.DataFrame(), case_control
    out = pd.concat(rows, ignore_index=True)
    return out, case_control


# ── Analysis ───────────────────────────────────────────────────────────────────

def deployed_coef(feature):
    c = core.COEFFS_PITTSBURGH_PROXIMITY
    if feature == "wind_alignment":
        return c.get("wind_align_weighted")
    if feature == "multi_source_exposure":
        return c.get("multi_source_exposure")
    if feature == "precipitation_lag1":
        return None  # not in deployed model — purely exploratory
    return c.get(feature)


def univariate_screen(tbl):
    used = tbl[tbl["used"] == 1]
    avail = tbl[tbl["used"] == 0]
    out = []
    for f in ALL_FEATURES:
        if f not in tbl:
            continue
        u = pd.to_numeric(used[f], errors="coerce").dropna()
        a = pd.to_numeric(avail[f], errors="coerce").dropna()
        if len(u) == 0:
            continue
        row = {
            "feature": f,
            "used_mean": round(float(u.mean()), 4),
            "avail_mean": round(float(a.mean()), 4) if len(a) else np.nan,
            "n_used": int(len(u)),
            "n_avail": int(len(a)),
        }
        # point-biserial correlation (feature vs used label) when we have both classes
        if len(a) and tbl["used"].nunique() >= 2:
            x = pd.to_numeric(tbl[f], errors="coerce")
            valid = x.notna()
            if valid.sum() > 3 and tbl.loc[valid, "used"].nunique() >= 2:
                r = np.corrcoef(x[valid], tbl.loc[valid, "used"])[0, 1]
                row["corr_with_odor"] = round(float(r), 4)
        out.append(row)
    return pd.DataFrame(out)


def multivariate_fit(tbl, min_reports):
    """Logistic regression used ~ standardized features. Returns comparison table."""
    try:
        import statsmodels.api as sm
    except Exception:
        print("  ! statsmodels not installed — skipping multivariate fit.")
        return pd.DataFrame()

    feats = [f for f in ALL_FEATURES if f in tbl]
    d = tbl[feats + ["used"]].apply(pd.to_numeric, errors="coerce").dropna()
    n_used = int(d["used"].sum())
    n_total = len(d)
    if n_used < min_reports or d["used"].nunique() < 2:
        print(f"  ! not enough data for regression (used={n_used}, need ≥{min_reports} "
              f"with both classes). Univariate screen above is your guide for now.")
        return pd.DataFrame()

    # Standardize so coefficients are comparable in magnitude across variables.
    means, stds = d[feats].mean(), d[feats].std().replace(0, 1)
    Z = (d[feats] - means) / stds
    X = sm.add_constant(Z)
    try:
        fit = sm.Logit(d["used"], X).fit(disp=0, method="bfgs", maxiter=400)
    except Exception as e:
        print(f"  ! regression failed: {e}")
        return pd.DataFrame()

    rows = []
    for f in feats:
        # de-standardize the coefficient back to raw feature units for comparability
        beta_std = fit.params.get(f, np.nan)
        beta_raw = beta_std / stds[f]
        dep = deployed_coef(f)
        flag = ""
        if dep is not None and not np.isnan(beta_raw) and dep != 0:
            if (dep > 0) != (beta_raw > 0):
                flag += "SIGN FLIP "
            if abs(beta_raw / dep) > 3 or abs(beta_raw / dep) < 0.33:
                flag += "MAGNITUDE"
        rows.append({
            "feature": f,
            "deployed": round(dep, 6) if dep is not None else "— (not in model)",
            "calvert_est": round(float(beta_raw), 6),
            "p_value": round(float(fit.pvalues.get(f, np.nan)), 4),
            "flag": flag.strip() or "ok",
        })
    print(f"\n  Regression fit on n={n_total} day-rows ({n_used} odor / {n_total - n_used} control).")
    return pd.DataFrame(rows)


# ── Model generation, validation & install ─────────────────────────────────────

# Features that map onto the DEPLOYED model's coefficients (drop diagnostics-only
# distance_from_source and precipitation_lag1). wind_alignment → wind_align_weighted.
MODEL_FIT_FEATURES = WEATHER_FEATURES + ["multi_source_exposure", "wind_alignment"]


def _modeling_frame(tbl):
    d = tbl[MODEL_FIT_FEATURES + ["used", "severity"]].copy()
    d[MODEL_FIT_FEATURES] = d[MODEL_FIT_FEATURES].apply(pd.to_numeric, errors="coerce")
    return d.dropna(subset=MODEL_FIT_FEATURES + ["used"]).reset_index(drop=True)


def _sample_weights(y, severity):
    """Controls weight 1; odor days weighted by reported severity (default 3 if blank)."""
    sev = pd.to_numeric(severity, errors="coerce").fillna(3.0).to_numpy()
    w = np.ones(len(y))
    w[y == 1] = sev[y == 1]
    return w


def _deployed_z(d, coeffs, offset):
    z = np.full(len(d), coeffs.get("const", 0.0), dtype=float)
    for f in WEATHER_FEATURES:
        col = d[f].to_numpy()
        if f == "atmospheric_pressure":
            z += coeffs.get(f, 0.0) * (col - offset)
        else:
            z += coeffs.get(f, 0.0) * col
    z += coeffs.get("multi_source_exposure", 0.0) * d["multi_source_exposure"].to_numpy()
    z += coeffs.get("wind_align_weighted", 0.0) * d["wind_alignment"].to_numpy()
    return z


def crossval_compare(tbl, offset, n_splits=5):
    """5-fold CV AUC for a locally-fit model vs the deployed model on the same data."""
    from sklearn.model_selection import StratifiedKFold
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    d = _modeling_frame(tbl)
    y = d["used"].astype(int).to_numpy()
    if y.sum() < 4 or (y == 0).sum() < 4:
        return None
    splits = min(n_splits, int(y.sum()))
    skf = StratifiedKFold(n_splits=splits, shuffle=True, random_state=0)
    X = d[MODEL_FIT_FEATURES]
    cand = np.zeros(len(d))
    for tr, te in skf.split(X, y):
        sc = StandardScaler().fit(X.iloc[tr])
        w = _sample_weights(y[tr], d["severity"].iloc[tr])
        clf = LogisticRegression(class_weight="balanced", max_iter=1000)
        clf.fit(sc.transform(X.iloc[tr]), y[tr], sample_weight=w)
        cand[te] = clf.decision_function(sc.transform(X.iloc[te]))
    dep = _deployed_z(d, core.COEFFS_PITTSBURGH_PROXIMITY, offset)
    return float(roc_auc_score(y, cand)), float(roc_auc_score(y, dep)), int(y.sum()), len(d)


def fit_full_model(tbl, offset):
    """Fit on ALL data; return a deployable coefficient dict (offset pre-baked)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    d = _modeling_frame(tbl)
    y = d["used"].astype(int).to_numpy()
    X = d[MODEL_FIT_FEATURES]
    sc = StandardScaler().fit(X)
    w = _sample_weights(y, d["severity"])
    clf = LogisticRegression(class_weight="balanced", max_iter=1000).fit(
        sc.transform(X), y, sample_weight=w)

    coef_std = clf.coef_[0]
    means, scales = sc.mean_, sc.scale_
    coef_raw = coef_std / scales
    const = float(clf.intercept_[0] - np.sum(coef_std * means / scales))

    out = {"const": const}
    for f, c in zip(MODEL_FIT_FEATURES, coef_raw):
        key = "wind_align_weighted" if f == "wind_alignment" else f
        out[key] = float(c)
    # Frontend computes atmospheric_pressure*(pressure - offset); we fit on raw
    # pressure, so fold the offset into the intercept for a drop-in coefficient set.
    out["const"] += out.get("atmospheric_pressure", 0.0) * offset
    return out


def install_model(candidate, meta, assume_yes=False, assume_no=False):
    print("\n" + "-" * 72)
    print("PROPOSED DATA-FITTED CALVERT MODEL")
    print("-" * 72)
    for k, v in candidate.items():
        print(f"  {k:<28}{v:+.6f}")
    print(f"\n  Based on {meta['n_reports']} reports | "
          f"CV-AUC {meta['cv_auc_candidate']:.3f} (deployed {meta['cv_auc_deployed']:.3f})")

    if assume_no:
        print("\n  --no specified — not installing.")
        return False
    if not assume_yes:
        if not sys.stdin.isatty():
            print("\n  Non-interactive shell. Re-run with --yes to install, or run "
                  "interactively to get the prompt. Not installing.")
            return False
        try:
            ans = input("\n  Add this model to the forecaster as a selectable mode? [y/N]: ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            print("  Not installed.")
            return False

    payload = {**meta, "coefficients": candidate}
    with open(core.FITTED_MODEL_PATH, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\n  ✅ Installed → {core.FITTED_MODEL_PATH}")
    print("  Next: run  .venv/bin/python generate_site.py  to rebuild the dashboard,")
    print("  then commit calvert_fitted_model.json. It appears as 'Calvert City "
          "(Data-Fitted)' and becomes the default mode.")
    return True


def generate_and_offer(tbl, offset, args):
    print("\n" + "=" * 72)
    print("MODEL GENERATION  (can a Calvert-fitted model beat the deployed one?)")
    print("=" * 72)
    cv = crossval_compare(tbl, offset)
    if cv is None:
        print("  Not enough odor/control days for a cross-validated fit yet.")
        return
    cand_auc, dep_auc, n_odor, n_rows = cv
    print(f"  Reports (odor days): {n_odor}   modeling rows: {n_rows}")
    print(f"  Cross-validated AUC — candidate: {cand_auc:.3f}   deployed: {dep_auc:.3f}   "
          f"Δ {cand_auc - dep_auc:+.3f}")

    gates = {
        f"reports ≥ {args.install_min_reports}": n_odor >= args.install_min_reports,
        f"candidate AUC ≥ {args.auc_floor}": cand_auc >= args.auc_floor,
        f"beats deployed by ≥ {args.auc_margin}": cand_auc >= dep_auc + args.auc_margin,
    }
    print("\n  Quality gates:")
    for name, ok in gates.items():
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")

    if not all(gates.values()):
        print("\n  → Gates not all passed — keeping the deployed model. Collect more "
              "reports (or the local data simply isn't better) and re-run.")
        return

    candidate = fit_full_model(tbl, offset)
    meta = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "n_reports": n_odor,
        "cv_auc_candidate": round(cand_auc, 4),
        "cv_auc_deployed": round(dep_auc, 4),
        "note": ("Fitted from local Calvert reports (use-vs-availability / case-control, "
                 "severity-weighted). Const pre-adjusted for PRESSURE_ELEVATION_OFFSET."),
    }
    install_model(candidate, meta, assume_yes=args.yes, assume_no=args.no)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(ROOT, "calvert_tester_logs.db"))
    ap.add_argument("--csv", default=None, help="Local Google-Form responses CSV")
    ap.add_argument("--sheet-url", default=None, help="Published Google Sheet CSV URL")
    ap.add_argument("--background-days", type=int, default=365,
                    help="Control-day window for presence-only (use-availability) mode")
    ap.add_argument("--min-reports", type=int, default=30,
                    help="Min odor days before a multivariate regression is attempted")
    ap.add_argument("--install-min-reports", type=int, default=50,
                    help="Min odor days before offering to install a fitted model")
    ap.add_argument("--auc-floor", type=float, default=0.60,
                    help="Candidate must reach at least this cross-validated AUC")
    ap.add_argument("--auc-margin", type=float, default=0.02,
                    help="Candidate must beat the deployed model's AUC by at least this")
    ap.add_argument("--yes", action="store_true", help="Install fitted model without prompting")
    ap.add_argument("--no", action="store_true", help="Never install (analysis only)")
    ap.add_argument("--out", default=os.path.join(ROOT, "scratch", "calvert_analysis"))
    args = ap.parse_args()

    print("=" * 72)
    print("CALVERT CITY REPORT → COEFFICIENT ANALYSIS")
    print("=" * 72)

    frames = []
    db = load_reports_from_db(args.db)
    if not db.empty:
        print(f"  Loaded {len(db)} reports from tester db.")
        frames.append(db)
    if args.csv:
        c = load_reports_from_csv(args.csv)
        print(f"  Loaded {len(c)} reports from CSV {args.csv}.")
        frames.append(c)
    if args.sheet_url:
        c = load_reports_from_csv(args.sheet_url, is_url=True)
        print(f"  Loaded {len(c)} reports from published sheet.")
        frames.append(c)

    if not frames:
        print("\n  No report sources found. Provide --csv or --sheet-url, or populate "
              "the tester db. Nothing to analyze.")
        return

    reports = normalize_reports(pd.concat(frames, ignore_index=True))
    reports = reports.dropna(subset=["latitude", "longitude"])
    print(f"\n  {len(reports)} usable reports after normalization "
          f"({reports['date'].min()} → {reports['date'].max()}).")

    if len(reports) < 3:
        print("\n  Fewer than 3 reports — far too few to infer anything. Re-run once "
              "you've collected more (aim for 30+ odor days for a real regression).")
        return

    cache = _load_cache()
    print("\n  Fetching weather (ERA5 archive) for report + background days …")
    tbl, case_control = build_used_available(reports, args.background_days, cache)
    _save_cache(cache)
    if tbl.empty:
        print("  ! No weather data assembled. Check connectivity / coordinates.")
        return

    mode = "CASE-CONTROL (odor yes/no)" if case_control else "USE-vs-AVAILABILITY (presence-only)"
    print(f"\n  Analysis mode: {mode}")
    print(f"  Modeling rows: {len(tbl)}  (odor days: {int(tbl['used'].sum())})")

    print("\n" + "-" * 72)
    print("UNIVARIATE SCREEN  (does each variable differ on odor days?)")
    print("-" * 72)
    uni = univariate_screen(tbl)
    print(uni.to_string(index=False) if not uni.empty else "  (no features)")

    print("\n" + "-" * 72)
    print("MULTIVARIATE COMPARISON vs DEPLOYED COEFFICIENTS")
    print("-" * 72)
    comp = multivariate_fit(tbl, args.min_reports)
    if not comp.empty:
        print(comp.to_string(index=False))
        flagged = comp[comp["flag"] != "ok"]
        print("\n  → Variables worth revisiting:",
              ", ".join(flagged["feature"]) if not flagged.empty else "none "
              "(Calvert data is consistent with the deployed coefficients).")
        print("  → REMINDER: these are suggestions. Review p-values and sample size "
              "before editing odor_forecast_core.py. Nothing was changed automatically.")

    # Try to generate a better Calvert-fitted model and offer to install it.
    generate_and_offer(tbl, core.PRESSURE_ELEVATION_OFFSET, args)

    # Persist outputs
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tbl.to_csv(args.out + "_features.csv", index=False)
    summary = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "n_reports": int(len(reports)),
        "n_modeling_rows": int(len(tbl)),
        "n_odor_days": int(tbl["used"].sum()),
        "univariate": uni.to_dict(orient="records"),
        "comparison": comp.to_dict(orient="records") if not comp.empty else [],
    }
    with open(args.out + "_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    print(f"\n  Saved {args.out}_features.csv and {args.out}_summary.json")


if __name__ == "__main__":
    main()
