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
        locs.append({
            "zip": name.split(" ")[1],
            "name": name.split("(")[1].rstrip(")").strip() if "(" in name else name,
            "lat": lat, "lon": lon,
        })
    return locs


def build_feature_payload(df, dates_sorted):
    features = {}
    for d in dates_sorted:
        day = df[df["date"] == d]
        per_zip = {}
        for _, row in day.iterrows():
            zip_code = row["location"].split(" ")[1]
            aligned = core.check_wind_alignment(row["wind_direction"], row["location"])
            per_zip[zip_code] = {
                "aligned": bool(aligned),
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
    }
    return {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Open-Meteo (NWP + ERA5)",
        "pressure_offset": core.PRESSURE_ELEVATION_OFFSET,
        "coeffs": {
            "estimated_calvert": core.COEFFS_EST_CALVERT,
            "exact_pittsburgh": core.COEFFS_PITTSBURGH,
        },
        "mode_labels": {
            "estimated_calvert": "Estimated Calvert City",
            "exact_pittsburgh": "Exact Pittsburgh Model",
        },
        "custom_slider_ranges": custom_ranges,
        "wind_defaults": {"filter": True, "penalty_pct": 75, "boost": 1.0},
    }


def main(output_dir=None):
    output_dir = output_dir or os.path.join(ROOT, "docs", "data")
    os.makedirs(output_dir, exist_ok=True)

    fdf, f_mock = core.fetch_forecasts(core.LOCATIONS)
    hdf, h_mock = core.fetch_historical_weather(core.LOCATIONS)
    if f_mock or h_mock:
        raise RuntimeError("Open-Meteo returned no live data (mock fallback); refusing to overwrite good data.")

    f_dates = sorted(fdf["date"].unique())
    h_dates = sorted(hdf["date"].unique())

    with open(os.path.join(output_dir, "forecast.json"), "w") as fh:
        json.dump(build_feature_payload(fdf, f_dates), fh)
    with open(os.path.join(output_dir, "historical.json"), "w") as fh:
        json.dump(build_feature_payload(hdf, h_dates), fh)
    with open(os.path.join(output_dir, "meta.json"), "w") as fh:
        json.dump(build_meta(), fh, indent=2)

    # Copy the ZIP boundary polygons next to index.html for Leaflet
    src_geo = os.path.join(ROOT, "calvert_zips.geojson")
    if os.path.exists(src_geo):
        shutil.copy(src_geo, os.path.join(ROOT, "docs", "calvert_zips.geojson"))

    print(f"Wrote forecast ({len(f_dates)}d), historical ({len(h_dates)}d), meta to {output_dir}")


if __name__ == "__main__":
    main()
