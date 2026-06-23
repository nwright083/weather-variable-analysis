import os
import sys
import json
import tempfile
import numpy as np
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
            })
    return pd.DataFrame(rows)


def test_build_feature_payload_schema():
    dates = ["2026-06-24", "2026-06-25"]
    df = _fake_df(dates)
    payload = generate_site.build_feature_payload(df, dates)
    assert payload["dates"] == dates
    assert {l["zip"] for l in payload["locations"]} == {"42029","42025","42045","42081","42058","42001","42003"}
    cell = payload["features"]["2026-06-24"]["42029"]
    for k in ["aligned","temp","temp_sq","solar","rh","wind_speed","wind_dir","precip","dtr","blh","pressure"]:
        assert k in cell, f"missing {k}"
    assert isinstance(cell["aligned"], bool)


def test_build_meta_has_coeffs_and_offset():
    meta = generate_site.build_meta()
    assert meta["pressure_offset"] == generate_site.core.PRESSURE_ELEVATION_OFFSET
    assert "estimated_calvert" in meta["coeffs"]
    assert "exact_pittsburgh" in meta["coeffs"]
    assert meta["coeffs"]["exact_pittsburgh"]["const"] == generate_site.core.COEFFS_PITTSBURGH["const"]
    assert set(meta["mode_labels"]) == {"estimated_calvert", "exact_pittsburgh"}
