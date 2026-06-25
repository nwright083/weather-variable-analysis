import os
import sys
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_site
import odor_forecast_core as core


def _fake_df(dates):
    rows = []
    for loc in generate_site.core.LOCATIONS:
        lat, lon = generate_site.core.LOCATIONS[loc]["coords"]
        for d in dates:
            rows.append({
                'date': d, 'location': loc, 'latitude': lat, 'longitude': lon,
                'temperature': 75.0, 'temp_min': 67.0, 'temp_max': 83.0,
                'temperature_squared': 75.0 ** 2, 'solar_radiation': 180.0,
                'relative_humidity': 70.0, 'wind_speed': 3.0, 'wind_direction': 200.0,
                'precipitation': 0.0, 'diurnal_temperature_range': 16.0,
                'boundary_layer_height': 800.0, 'atmospheric_pressure': 1005.0,
                'bearing_from_source': generate_site.core.calculate_bearing(lat, lon),
                'distance_from_source': 5.0,
            })
    return pd.DataFrame(rows)


def test_build_feature_payload_schema():
    dates = ["2026-06-24", "2026-06-25"]
    df = _fake_df(dates)
    payload = generate_site.build_feature_payload(df, dates)
    assert payload["dates"] == dates
    # Locations should now use GEOID keys (11-digit tract IDs)
    loc_ids = {l["zip"] for l in payload["locations"]}
    assert len(loc_ids) == len(generate_site.core.LOCATIONS), "Expected one entry per LOCATION"
    # All IDs should start with "21" (KY state FIPS) for tract format, or be legacy ZIP codes
    for lid in loc_ids:
        assert lid.startswith("21") or lid.isdigit(), f"Unexpected location id format: {lid}"
    # Pick the first location id to inspect
    first_id = list(payload["features"]["2026-06-24"].keys())[0]
    cell = payload["features"]["2026-06-24"][first_id]
    for k in ["aligned","wind_alignment","distance","temp","temp_sq","solar","rh","wind_speed","wind_dir","precip","dtr","blh","pressure"]:
        assert k in cell, f"missing {k}"
    assert isinstance(cell["aligned"], bool)
    assert isinstance(cell["wind_alignment"], float), "Expected wind_alignment float in cell"
    assert 0.0 <= cell["wind_alignment"] <= 1.0, f"wind_alignment out of range: {cell['wind_alignment']}"


def test_build_meta_has_coeffs_and_offset():
    meta = generate_site.build_meta()
    assert meta["pressure_offset"] == generate_site.core.PRESSURE_ELEVATION_OFFSET
    assert "estimated_calvert" in meta["coeffs"]
    assert "exact_pittsburgh" in meta["coeffs"]
    assert meta["coeffs"]["exact_pittsburgh"]["const"] == generate_site.core.COEFFS_PITTSBURGH["const"]
    assert {"estimated_calvert", "exact_pittsburgh", "pittsburgh_proximity"} <= set(meta["mode_labels"])
    assert "pittsburgh_proximity" in meta["coeffs"]
    assert meta["coeffs"]["pittsburgh_proximity"]["multi_source_exposure"] == generate_site.core.COEFFS_PITTSBURGH_PROXIMITY["multi_source_exposure"]


def test_build_meta_model_metrics():
    meta = generate_site.build_meta()
    # model_metrics present when model_metrics.json exists at repo root
    import os
    metrics_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model_metrics.json")
    if not os.path.exists(metrics_path):
        return  # graceful no-op when file absent (e.g. CI without training data)
    mm = meta.get("model_metrics")
    assert mm is not None, "model_metrics missing from meta despite model_metrics.json existing"
    assert "models" in mm
    for model_key in ("exact_pittsburgh", "pittsburgh_proximity", "estimated_calvert"):
        assert model_key in mm["models"], f"missing model key: {model_key}"
        m = mm["models"][model_key]
        assert "fpr" in m and "tpr" in m and "auc" in m, f"{model_key} missing curve arrays"
        assert isinstance(m["fpr"], list) and len(m["fpr"]) > 5
        assert 0.5 < m["auc"] <= 1.0, f"{model_key} AUC out of range: {m['auc']}"


def _fake_hourly_df(dates):
    """Synthetic hourly DataFrame mirroring fetch_hourly_forecasts output schema."""
    rows = []
    for loc_name, loc_info in core.LOCATIONS.items():
        lat, lon = loc_info["coords"]
        parts = loc_name.split(" ", 2)
        loc_id = parts[1] if len(parts) > 1 else loc_name
        distance = core.calculate_distance(lat, lon)
        bearing = core.calculate_bearing(lat, lon)
        for d in dates:
            for h in range(24):
                temp = 78.0 + h * 0.1
                rows.append({
                    'datetime': f"{d}T{h:02d}:00",
                    'date': d, 'hour': h,
                    'loc_id': loc_id, 'location': loc_name,
                    'temperature': temp,
                    'temperature_squared': temp ** 2,
                    'solar_radiation': 200.0 if 6 <= h <= 18 else 0.0,
                    'relative_humidity': 65.0,
                    'wind_speed': 4.0,
                    'wind_direction': 200.0,
                    'precipitation': 0.0,
                    'dtr': 16.0,
                    'boundary_layer_height': 1000.0,
                    'atmospheric_pressure': 1005.0,
                    'distance_from_source': distance,
                    'bearing_from_source': bearing,
                    'wind_alignment': 0.5,
                    'aligned': False,
                })
    return pd.DataFrame(rows)


def test_build_hourly_payload_schema():
    dates = ["2026-06-24", "2026-06-25"]
    df = _fake_hourly_df(dates)
    payload = generate_site.build_hourly_payload(df)

    assert payload["dates"] == dates, "dates list must match input"
    # 2 days × 24 hours = 48 datetime slots
    assert len(payload["datetimes"]) == 48, f"Expected 48 datetimes, got {len(payload['datetimes'])}"
    # Spot-check first and last datetime
    assert payload["datetimes"][0] == "2026-06-24T00:00"
    assert payload["datetimes"][-1] == "2026-06-25T23:00"

    # All datetime keys present in features
    for dt in payload["datetimes"]:
        assert dt in payload["features"], f"Missing datetime key: {dt}"

    # Every location present in each hour slot, with required cell keys
    n_locs = len(core.LOCATIONS)
    required_keys = {"aligned", "wind_alignment", "distance", "temp", "temp_sq",
                     "solar", "rh", "wind_speed", "wind_dir", "precip", "dtr", "blh", "pressure"}
    for dt in payload["datetimes"][:4]:  # check first 4 slots to keep test fast
        hour_feats = payload["features"][dt]
        assert len(hour_feats) == n_locs, f"{dt}: expected {n_locs} tracts, got {len(hour_feats)}"
        first_cell = next(iter(hour_feats.values()))
        missing = required_keys - set(first_cell.keys())
        assert not missing, f"Missing cell keys in {dt}: {missing}"
        assert isinstance(first_cell["aligned"], bool)
        assert 0.0 <= first_cell["wind_alignment"] <= 1.0
        assert first_cell["dtr"] == 16.0, "DTR should match the constant we set"

    # Locations directory matches LOCATIONS
    loc_ids = {l["zip"] for l in payload["locations"]}
    assert len(loc_ids) == n_locs
