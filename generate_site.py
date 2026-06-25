"""Headless generator for the static odor-risk forecast site.

Fetches weather via odor_forecast_core, emits RAW model features (not ORI) plus
a meta file with coefficients, so the browser can compute ORI live for any mode.
"""
import os
import json
import shutil
import datetime

import odor_forecast_core as core

ROOT = os.path.dirname(os.path.abspath(__file__))


def _location_directory():
    locs = []
    for name, info in core.LOCATIONS.items():
        lat, lon = info["coords"]
        # Format: "TRACT {GEOID} ({Name})" or old "ZIP {code} ({Name})"
        parts = name.split(" ", 2)
        id_key = parts[1] if len(parts) > 1 else name
        display_name = name.split("(")[1].rstrip(")").strip() if "(" in name else name
        locs.append({
            "id": id_key,    # GEOID (e.g. "21157950100") or ZIP code
            "zip": id_key,   # keep "zip" key for backward compat
            "name": display_name,
            "lat": lat, "lon": lon,
        })
    return locs


def build_feature_payload(df, dates_sorted):
    features = {}
    for d in dates_sorted:
        day = df[df["date"] == d]
        per_zip = {}
        for _, row in day.iterrows():
            loc_name = row["location"]
            parts = loc_name.split(" ", 2)
            loc_id = parts[1] if len(parts) > 1 else loc_name  # GEOID or ZIP

            aligned = core.check_wind_alignment(row["wind_direction"], row["location"])

            # Compute continuous wind alignment (use pre-computed column if available)
            if "wind_alignment" in row and not (isinstance(row["wind_alignment"], float) and str(row["wind_alignment"]) == "nan"):
                alignment = round(float(row["wind_alignment"]), 3)
            elif "bearing_from_source" in row:
                alignment = round(core.compute_continuous_wind_alignment(
                    row["wind_direction"], row["bearing_from_source"]
                ), 3)
            else:
                alignment = 0.5

            per_zip[loc_id] = {
                "aligned": bool(aligned),
                "wind_alignment": alignment,
                "distance": round(float(row["distance_from_source"]), 2),
                "temp": round(float(row["temperature"]), 2),
                "temp_sq": round(float(row["temperature_squared"]), 2),
                "solar": round(float(row["solar_radiation"]), 2),
                "rh": round(float(row["relative_humidity"]), 2),
                "wind_speed": round(float(row["wind_speed"]), 2),
                "wind_dir": round(float(row["wind_direction"]), 1),
                "precip": round(float(row["precipitation"]), 3),
                "dtr": round(float(row["diurnal_temperature_range"]), 2),
                "blh": round(float(row["boundary_layer_height"]), 1),
                "pressure": round(float(row["atmospheric_pressure"]), 2),
            }
        features[d] = per_zip
    return {"dates": list(dates_sorted), "locations": _location_directory(), "features": features}


def build_hourly_payload(hourly_df):
    """Build per-hour feature payload for the Hourly tab (lazy-loaded as hourly.json)."""
    datetimes = sorted(hourly_df['datetime'].unique())
    dates = sorted(hourly_df['date'].unique())

    # Group by datetime once for efficiency
    grouped = hourly_df.groupby('datetime', sort=True)
    features = {}
    for dt, group in grouped:
        per_tract = {}
        for _, row in group.iterrows():
            loc_id = row['loc_id']
            per_tract[loc_id] = {
                "aligned": bool(row['aligned']),
                "wind_alignment": round(float(row['wind_alignment']), 3),
                "distance": round(float(row['distance_from_source']), 2),
                "temp": round(float(row['temperature']), 1),
                "temp_sq": round(float(row['temperature_squared']), 1),
                "solar": round(float(row['solar_radiation']), 1),
                "rh": round(float(row['relative_humidity']), 1),
                "wind_speed": round(float(row['wind_speed']), 2),
                "wind_dir": round(float(row['wind_direction']), 1),
                "precip": round(float(row['precipitation']), 3),
                "dtr": round(float(row['dtr']), 2),
                "blh": round(float(row['boundary_layer_height']), 1),
                "pressure": round(float(row['atmospheric_pressure']), 2),
            }
        features[dt] = per_tract

    return {
        "dates": list(dates),
        "datetimes": list(datetimes),
        "locations": _location_directory(),
        "features": features,
    }


def build_meta():
    custom_ranges = {
        "const": [-30.0, 30.0, 0.1],
        "temperature": [-0.5, 0.5, 0.001],
        "temperature_squared": [-0.005, 0.005, 0.00001],
        "solar_radiation": [-0.1, 0.1, 0.001],
        "relative_humidity": [-0.2, 0.2, 0.001],
        "wind_speed": [-0.5, 0.5, 0.001],
        "precipitation": [-2.0, 2.0, 0.01],
        "diurnal_temperature_range": [-0.5, 0.5, 0.001],
        "boundary_layer_height": [-0.005, 0.005, 0.00001],
        "atmospheric_pressure": [-0.1, 0.1, 0.001],
        # Proximity regression terms (active when coefficients are non-zero in custom mode)
        "multi_source_exposure": [-5.0, 20.0, 0.1],
        "wind_align_weighted": [-5.0, 5.0, 0.05],
        # Post-hoc spatial adjustment parameters (shown in custom mode Spatial Adjustments section)
        "penalty_pct": [0, 100, 5],
        "boost": [1.0, 3.0, 0.05],
        "decay_rate": [0.0, 0.5, 0.01],
    }
    coeffs = {
        "estimated_calvert": core.COEFFS_EST_CALVERT,
        "exact_pittsburgh": core.COEFFS_PITTSBURGH,
        "pittsburgh_proximity": core.COEFFS_PITTSBURGH_PROXIMITY,
    }
    mode_labels = {
        "estimated_calvert": "Estimated Calvert City",
        "exact_pittsburgh": "Exact Pittsburgh Model",
        "pittsburgh_proximity": "Pittsburgh Proximity-Enhanced",
    }
    default_mode = "pittsburgh_proximity"

    # Expose a locally-fitted Calvert model if analyze_calvert_reports.py installed one.
    if core.COEFFS_CALVERT_FITTED:
        coeffs["calvert_fitted"] = core.COEFFS_CALVERT_FITTED
        label = "Calvert City (Data-Fitted)"
        meta = core.CALVERT_FITTED_META or {}
        if meta.get("n_reports"):
            label += f" — {meta['n_reports']} reports"
        mode_labels["calvert_fitted"] = label
        default_mode = "calvert_fitted"  # prefer the data-fitted model once it exists

    meta = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Open-Meteo (NWP + ERA5)",
        "pressure_offset": core.PRESSURE_ELEVATION_OFFSET,
        "default_mode": default_mode,
        "coeffs": coeffs,
        "mode_labels": mode_labels,
        "fitted_meta": core.CALVERT_FITTED_META,
        "custom_slider_ranges": custom_ranges,
        "wind_defaults": {"filter": True, "penalty_pct": 75, "boost": 1.0, "continuous_mode": True},
        "distance_defaults": {"enabled": True, "rate": 0.02},
    }
    metrics_path = os.path.join(ROOT, "model_metrics.json")
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            meta["model_metrics"] = json.load(f)
    return meta


def main(output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "docs", "data")
    os.makedirs(output_dir, exist_ok=True)

    fdf, f_mock    = core.fetch_forecasts(core.LOCATIONS)
    hdf, h_mock    = core.fetch_historical_weather(core.LOCATIONS)
    hrdf, hr_mock  = core.fetch_hourly_forecasts(core.LOCATIONS)
    if f_mock or h_mock or hr_mock:
        raise RuntimeError("Open-Meteo returned no live data (mock fallback); refusing to overwrite good data.")

    f_dates  = sorted(fdf["date"].unique())
    h_dates  = sorted(hdf["date"].unique())
    hr_dates = sorted(hrdf["date"].unique())

    with open(os.path.join(output_dir, "forecast.json"), "w") as fh:
        json.dump(build_feature_payload(fdf, f_dates), fh)
    with open(os.path.join(output_dir, "historical.json"), "w") as fh:
        json.dump(build_feature_payload(hdf, h_dates), fh)
    with open(os.path.join(output_dir, "hourly.json"), "w") as fh:
        json.dump(build_hourly_payload(hrdf), fh)
    with open(os.path.join(output_dir, "meta.json"), "w") as fh:
        json.dump(build_meta(), fh, indent=2)

    # Copy tracts geojson (prefer tracts, fall back to zips)
    for geo_name in ["calvert_tracts.geojson", "calvert_zips.geojson"]:
        src_geo = os.path.join(ROOT, geo_name)
        if os.path.exists(src_geo):
            dst_name = "calvert_areas.geojson"
            shutil.copy(src_geo, os.path.join(ROOT, "docs", dst_name))
            break

    print(f"Wrote forecast ({len(f_dates)}d), historical ({len(h_dates)}d), "
          f"hourly ({len(hr_dates)}d × 24h), meta to {output_dir}")


if __name__ == "__main__":
    main()
