import os
import sys
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_site


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
