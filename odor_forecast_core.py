"""Pure odor-risk forecasting logic — no Streamlit, no import-time side effects.

Shared by the Streamlit app (calvert_odor_forecaster.py) and the static-site
generator (generate_site.py). This module is the single source of truth for the
model coefficients and the PRESSURE_ELEVATION_OFFSET.
"""
import math
import hashlib
import datetime
import numpy as np
import pandas as pd
import requests

# Center coordinates of the Calvert City Industrial Complex
IND_LAT = 37.0486
IND_LON = -88.3480

# Elevation-adjusted pressure offset (cross-city transfer correction):
# Pittsburgh training mean surface pressure = 980.93 hPa (~370 m ASL);
# Calvert City / western KY mean ≈ 998.3 hPa (~115 m ASL). Subtracting this offset
# expresses Calvert pressure in Pittsburgh's training frame, preserving synoptic
# anomaly signal while removing the elevation artifact.
PRESSURE_ELEVATION_OFFSET = 17.4  # hPa

# Surrounding study locations mapped to Census Tracts across Marshall, McCracken, and Livingston counties
# GEOIDs are 11-digit 2020 Census Tract identifiers (STATE 2 + COUNTY 3 + TRACT 6)
LOCATIONS = {
    "TRACT 21139040100 (Tract Census Tract 401, Livingston Co.)": {"coords": (37.2777, -88.3421)},
    "TRACT 21139040201 (Tract Census Tract 402.01, Livingston Co.)": {"coords": (37.0833, -88.4319)},
    "TRACT 21139040202 (Tract Census Tract 402.02, Livingston Co.)": {"coords": (37.1057, -88.2843)},
    "TRACT 21145030100 (Tract Census Tract 301, McCracken Co.)": {"coords": (37.0628, -88.5698)},
    "TRACT 21145030200 (Tract Census Tract 302, McCracken Co.)": {"coords": (37.0706, -88.5938)},
    "TRACT 21145030300 (Tract Census Tract 303, McCracken Co.)": {"coords": (37.0916, -88.5992)},
    "TRACT 21145030400 (Tract Census Tract 304, McCracken Co.)": {"coords": (37.1041, -88.6260)},
    "TRACT 21145030500 (Tract Census Tract 305, McCracken Co.)": {"coords": (37.0830, -88.6155)},
    "TRACT 21145030600 (Tract Census Tract 306, McCracken Co.)": {"coords": (37.0611, -88.6107)},
    "TRACT 21145030700 (Tract Census Tract 307, McCracken Co.)": {"coords": (37.0774, -88.6334)},
    "TRACT 21145030800 (Tract Census Tract 308, McCracken Co.)": {"coords": (37.0724, -88.6556)},
    "TRACT 21145030900 (Tract Census Tract 309, McCracken Co.)": {"coords": (37.0502, -88.6305)},
    "TRACT 21145031000 (Tract Census Tract 310, McCracken Co.)": {"coords": (37.0332, -88.5806)},
    "TRACT 21145031100 (Tract Census Tract 311, McCracken Co.)": {"coords": (37.0098, -88.5185)},
    "TRACT 21145031200 (Tract Census Tract 312, McCracken Co.)": {"coords": (36.9868, -88.5832)},
    "TRACT 21145031301 (Tract Census Tract 313.01, McCracken Co.)": {"coords": (37.0423, -88.6730)},
    "TRACT 21145031302 (Tract Census Tract 313.02, McCracken Co.)": {"coords": (37.0211, -88.6825)},
    "TRACT 21145031401 (Tract Census Tract 314.01, McCracken Co.)": {"coords": (37.1112, -88.6781)},
    "TRACT 21145031402 (Tract Census Tract 314.02, McCracken Co.)": {"coords": (37.0651, -88.6984)},
    "TRACT 21145031501 (Tract Census Tract 315.01, McCracken Co.)": {"coords": (37.1492, -88.8275)},
    "TRACT 21145031502 (Tract Census Tract 315.02, McCracken Co.)": {"coords": (37.0609, -88.7955)},
    "TRACT 21145031600 (Tract Census Tract 316, McCracken Co.)": {"coords": (36.9842, -88.7613)},
    "TRACT 21157950101 (Tract Census Tract 9501.01, Marshall Co.)": {"coords": (37.0218, -88.4076)},
    "TRACT 21157950102 (Tract Census Tract 9501.02, Marshall Co.)": {"coords": (37.0258, -88.3373)},
    "TRACT 21157950200 (Tract Census Tract 9502, Marshall Co.)": {"coords": (36.9491, -88.4127)},
    "TRACT 21157950300 (Tract Census Tract 9503, Marshall Co.)": {"coords": (36.9448, -88.2930)},
    "TRACT 21157950400 (Tract Census Tract 9504, Marshall Co.)": {"coords": (36.8592, -88.3683)},
    "TRACT 21157950501 (Tract Census Tract 9505.01, Marshall Co.)": {"coords": (36.8400, -88.4406)},
    "TRACT 21157950502 (Tract Census Tract 9505.02, Marshall Co.)": {"coords": (36.7933, -88.3397)},
    "TRACT 21157950601 (Tract Census Tract 9506.01, Marshall Co.)": {"coords": (36.8958, -88.2429)},
    "TRACT 21157950602 (Tract Census Tract 9506.02, Marshall Co.)": {"coords": (36.8018, -88.2308)},
    "TRACT 21157950603 (Tract Census Tract 9506.03, Marshall Co.)": {"coords": (36.8306, -88.1830)},
}


def _tract_id_from_location(location_name):
    """Extract GEOID from 'TRACT 21157XXXXXX (Name)' format."""
    return location_name.split(" ")[1]

COEFFS_PITTSBURGH = {
    'const': 17.415789,
    'temperature': 0.114354,
    'temperature_squared': -0.000476,
    'solar_radiation': -0.013972,
    'relative_humidity': -0.057838,
    'wind_speed': -0.108479,
    'precipitation': -0.864070,
    'diurnal_temperature_range': 0.229181,
    'boundary_layer_height': -0.000410,
    'atmospheric_pressure': -0.017966,
}

COEFFS_EST_CALVERT = {
    'const': 18.000000,
    'temperature': 0.114354,
    'temperature_squared': -0.000476,
    'solar_radiation': -0.013972,
    'relative_humidity': -0.057838,
    'wind_speed': -0.150000,
    'precipitation': -0.864070,
    'diurnal_temperature_range': 0.229181,
    'boundary_layer_height': -0.000600,
    'atmospheric_pressure': -0.017966,
}

# Pittsburgh proximity-enhanced logit coefficients (zip-day panel, 2018-2026, 36 596 obs).
# Temporal dummies (dow_*, is_holiday) excluded — zeroed for de-biased Calvert City predictions.
# Proximity terms are integrated regression coefficients, not post-hoc multipliers:
#   multi_source_exposure: applied to exp(-0.02 * distance_from_source)  [single source for Calvert]
#   wind_align_weighted:   applied to continuous cosine alignment factor (0–1)
# ΔAIC vs weather-only = -889, ΔPseudo-R² = +0.022 (both features p < 0.0001).
# NOTE: The precipitation term is positive here because this model was trained on zip-level panel
# data (not city-wide daily), capturing local microclimatic correlations. Use with awareness.
COEFFS_PITTSBURGH_PROXIMITY = {
    'const': -12.666648271471834,
    'temperature': 0.018343042144885864,
    'temperature_squared': -0.00021423061641917800,
    'solar_radiation': -0.0009207391359819757,
    'relative_humidity': 0.004766342432915154,
    'wind_speed': -0.04088000835814254,
    'precipitation': 6.65637460426461,
    'diurnal_temperature_range': 0.23664438034852686,
    'boundary_layer_height': -8.362886723254747e-05,
    'atmospheric_pressure': 0.005515222566627884,
    'multi_source_exposure': 1.3318487869144982,
    'wind_align_weighted': 1.6800007018699348,
}

# Calvert City Proximity-Enhanced: Calvert terrain-adjusted weather coefficients
# (stronger wind_speed / boundary_layer_height sensitivity for flat rural terrain)
# combined with Pittsburgh's empirically trained proximity regression terms.
COEFFS_CALVERT_PROXIMITY = {
    **COEFFS_EST_CALVERT,
    'multi_source_exposure': COEFFS_PITTSBURGH_PROXIMITY['multi_source_exposure'],
    'wind_align_weighted': COEFFS_PITTSBURGH_PROXIMITY['wind_align_weighted'],
}


def calculate_bearing(lat2, lon2):
    lat1, lon1 = IND_LAT, IND_LON
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    bearing = math.degrees(math.atan2(dx, dy))
    return (bearing + 360) % 360


def calculate_distance(lat2, lon2):
    """Calculates the distance in miles from the industrial complex using the Haversine formula."""
    lat1, lon1 = IND_LAT, IND_LON
    R = 3958.8  # Earth radius in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def compute_continuous_wind_alignment(wind_from_deg, bearing_deg):
    """
    Returns a continuous wind alignment factor (0 to 1).

    1.0 = wind blows perfectly FROM the source TOWARD the receiver (ideal transport)
    0.0 = wind blows away from receiver (no transport)
    0.5 = crosswind (perpendicular)

    wind_from_deg: meteorological wind direction (direction wind comes FROM)
    bearing_deg: bearing from emission source to receiver location
    """
    wind_toward = (wind_from_deg + 180) % 360
    angle_diff = math.radians(wind_toward - bearing_deg)
    return (1 + math.cos(angle_diff)) / 2


# Sector bounds derived from calvert_zips.geojson via scratch/test_sectors.py;
# regenerate them if the geojson boundaries change.
def check_wind_alignment(wind_from, location_or_bearing, tolerance=10.0):
    # Fallback to centroid math if a bearing is passed directly (useful for tests/compat)
    if isinstance(location_or_bearing, (int, float)):
        opposite_bearing = (location_or_bearing + 180) % 360
        diff = abs(wind_from - opposite_bearing)
        diff = min(diff, 360.0 - diff)
        return diff <= 45.0  # Use default 45 degree tolerance for centroid math

    # Sector check for ZIP codes
    loc = str(location_or_bearing)
    if "42029" in loc:      # Calvert City residential center
        start, end = 150.0, 240.0
    elif "42025" in loc:    # Benton
        start, end = 132.1, 241.6
    elif "42045" in loc:    # Grand Rivers
        start, end = 26.9, 127.8
    elif "42081" in loc:    # Smithland
        start, end = 269.0, 58.5
    elif "42058" in loc:    # Ledbetter
        start, end = 256.3, 331.1
    elif "42001" in loc:    # Paducah
        start, end = 247.9, 288.6
    elif "42003" in loc:    # Reidland
        start, end = 230.0, 287.8
    else:
        return False

    # Expand sector by tolerance (incoming wind blows FROM opposite directions)
    # The wind direction (blows FROM) carrying odor is the opposite of the bearing sector:
    incoming_start = (start + 180) % 360
    incoming_end = (end + 180) % 360

    # We want to check if wind_from falls in [incoming_start - tolerance, incoming_end + tolerance]
    h_start = (incoming_start - tolerance) % 360
    h_end = (incoming_end + tolerance) % 360

    # Check if wind_from is inside this range
    if h_start <= h_end:
        return h_start <= wind_from <= h_end
    else:
        return wind_from >= h_start or wind_from <= h_end


def get_risk_meta(ori):
    if ori < 15.0:
        return "Clear / Low Risk", "badge-clear", [22, 163, 74]
    elif ori < 30.0:
        return "Moderate Risk", "badge-moderate", [202, 138, 4]
    elif ori < 50.0:
        return "Elevated Risk", "badge-elevated", [234, 88, 12]
    else:
        return "High Risk", "badge-high", [220, 38, 38]


def predict_ori(row, coeffs, *, use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0, use_distance_decay=False, distance_decay_rate=0.0, use_continuous_alignment=False):
    z = (
        coeffs['const'] +
        coeffs['temperature'] * row['temperature'] +
        coeffs['temperature_squared'] * row['temperature_squared'] +
        coeffs['solar_radiation'] * row['solar_radiation'] +
        coeffs['relative_humidity'] * row['relative_humidity'] +
        coeffs['wind_speed'] * row['wind_speed'] +
        coeffs['precipitation'] * row['precipitation'] +
        coeffs['diurnal_temperature_range'] * row['diurnal_temperature_range'] +
        coeffs['boundary_layer_height'] * row['boundary_layer_height'] +
        # Subtract elevation offset so Calvert pressure is in Pittsburgh's training frame.
        coeffs['atmospheric_pressure'] * (row['atmospheric_pressure'] - PRESSURE_ELEVATION_OFFSET)
    )
    if use_wind_filter:
        if use_continuous_alignment and 'wind_alignment' in row:
            # Continuous: interpolate between penalty and boost based on alignment
            alignment = float(row['wind_alignment'])
            effective_mult = wind_penalty + (wind_boost - wind_penalty) * alignment
            z += math.log(max(effective_mult, 1e-9))
        else:
            # Original discrete sector logic
            loc_val = row.get('location', row.get('bearing_from_source', 196.3))
            is_aligned = check_wind_alignment(row['wind_direction'], loc_val)
            if not is_aligned:
                z += math.log(max(wind_penalty, 1e-9))
            else:
                z += math.log(max(wind_boost, 1e-9))
    if use_distance_decay:
        dist = row.get('distance_from_source', None)
        if dist is None and 'latitude' in row and 'longitude' in row:
            dist = calculate_distance(row['latitude'], row['longitude'])
        if dist is not None:
            z -= distance_decay_rate * dist

    # Integrated proximity regression terms (present only in COEFFS_PITTSBURGH_PROXIMITY).
    # For Calvert City (single source) multi_source_exposure = exp(-0.02 * distance).
    if 'multi_source_exposure' in coeffs:
        dist = row.get('distance_from_source', None)
        if dist is None and 'latitude' in row and 'longitude' in row:
            dist = calculate_distance(row['latitude'], row['longitude'])
        if dist is not None:
            z += coeffs['multi_source_exposure'] * math.exp(-0.02 * dist)

    if 'wind_align_weighted' in coeffs:
        wind_align = row.get('wind_alignment', None)
        if wind_align is None:
            bearing = row.get('bearing_from_source',
                               calculate_bearing(row.get('latitude', IND_LAT),
                                                 row.get('longitude', IND_LON)))
            wind_align = compute_continuous_wind_alignment(
                row.get('wind_direction', 0.0), bearing)
        z += coeffs['wind_align_weighted'] * float(wind_align)

    z = max(-60.0, min(60.0, z))
    return round(100.0 / (1.0 + math.exp(-z)), 1)


def fetch_forecasts(locations):
    lats = [str(loc["coords"][0]) for loc in locations.values()]
    lons = [str(loc["coords"][1]) for loc in locations.values()]
    lat_param = ",".join(lats)
    lon_param = ",".join(lons)

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat_param}&longitude={lon_param}"
        f"&hourly=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,"
        f"wind_direction_10m,rain,shortwave_radiation,sunshine_duration,boundary_layer_height"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&forecast_days=16&timezone=America%2FChicago"
    )

    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        res_data = response.json()

        # Open-Meteo returns a list of dictionaries if multiple coordinates are requested
        forecast_list = res_data if isinstance(res_data, list) else [res_data]

        all_daily_records = []

        for idx, (loc_name, loc_info) in enumerate(locations.items()):
            loc_data = forecast_list[idx]
            hourly = loc_data.get("hourly", {})
            df_hourly = pd.DataFrame(hourly)
            df_hourly['time'] = pd.to_datetime(df_hourly['time'])
            df_hourly['date'] = df_hourly['time'].dt.strftime('%Y-%m-%d')

            # PBLH conversion (meters -> feet)
            if 'boundary_layer_height' in df_hourly.columns:
                df_hourly['boundary_layer_height_ft'] = df_hourly['boundary_layer_height'] * 3.28084
            else:
                df_hourly['boundary_layer_height_ft'] = 1500.0

            # Speed-weighted vector mean for wind direction — arithmetic mean of degrees
            # is invalid across the 0°/360° wrap (e.g. 350° and 10° average to 0°, not 180°).
            df_hourly['wind_u'] = df_hourly['wind_speed_10m'] * np.sin(np.radians(df_hourly['wind_direction_10m']))
            df_hourly['wind_v'] = df_hourly['wind_speed_10m'] * np.cos(np.radians(df_hourly['wind_direction_10m']))

            daily_df = df_hourly.groupby('date').agg({
                'temperature_2m': ['mean', 'min', 'max'],
                'rain': 'sum',
                'wind_speed_10m': 'mean',
                'wind_u': 'mean',
                'wind_v': 'mean',
                'relative_humidity_2m': 'mean',
                'surface_pressure': 'mean',
                'sunshine_duration': 'sum',
                'shortwave_radiation': 'mean',
                'boundary_layer_height_ft': 'mean'
            }).reset_index()

            daily_df.columns = [
                'date', 'temperature', 'temp_min', 'temp_max',
                'precipitation', 'wind_speed', 'wind_u', 'wind_v',
                'relative_humidity', 'atmospheric_pressure',
                'sunshine_duration', 'solar_radiation', 'boundary_layer_height'
            ]
            daily_df['wind_direction'] = np.degrees(np.arctan2(daily_df['wind_u'], daily_df['wind_v'])) % 360
            daily_df.drop(columns=['wind_u', 'wind_v'], inplace=True)

            daily_df['diurnal_temperature_range'] = daily_df['temp_max'] - daily_df['temp_min']
            daily_df['temperature_squared'] = daily_df['temperature'] ** 2
            daily_df['location'] = loc_name
            daily_df['latitude'] = loc_info["coords"][0]
            daily_df['longitude'] = loc_info["coords"][1]
            daily_df['bearing_from_source'] = calculate_bearing(loc_info["coords"][0], loc_info["coords"][1])
            daily_df['distance_from_source'] = calculate_distance(loc_info["coords"][0], loc_info["coords"][1])
            bearing_val = daily_df['bearing_from_source'].iloc[0]
            daily_df['wind_alignment'] = daily_df.apply(
                lambda r: compute_continuous_wind_alignment(r['wind_direction'], bearing_val), axis=1
            )

            all_daily_records.append(daily_df)

        combined_df = pd.concat(all_daily_records, ignore_index=True)
        return combined_df, False

    except Exception:
        # Build clean simulated fallback dataframe
        dates = [(datetime.date.today() + datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(16)]
        fallback_records = []
        for loc_name, loc_info in locations.items():
            state_seed = int(hashlib.md5(loc_name.encode()).hexdigest()[:8], 16) % 10000
            np.random.seed(state_seed)
            temps = np.random.uniform(65.0, 85.0, 16)
            dtrs = np.random.uniform(10.0, 22.0, 16)
            winds = np.random.uniform(1.5, 7.5, 16)
            wind_dirs = np.random.uniform(0, 360, 16)
            rh = np.random.uniform(50.0, 85.0, 16)
            press = np.random.uniform(1008.0, 1018.0, 16)
            sun_dur = np.random.uniform(20000.0, 40000.0, 16)
            rad = np.random.uniform(100.0, 300.0, 16)
            blh = np.random.choice([600.0, 1200.0, 2000.0], size=16, p=[0.2, 0.5, 0.3])
            rain = np.random.choice([0.0, 0.1, 0.3], size=16, p=[0.7, 0.2, 0.1])

            mock_data = {
                'date': dates,
                'temperature': temps,
                'temp_min': temps - dtrs / 2.0,
                'temp_max': temps + dtrs / 2.0,
                'precipitation': rain,
                'wind_speed': winds,
                'wind_direction': wind_dirs,
                'relative_humidity': rh,
                'atmospheric_pressure': press,
                'sunshine_duration': sun_dur,
                'solar_radiation': rad,
                'boundary_layer_height': blh
            }
            df_m = pd.DataFrame(mock_data)
            df_m['diurnal_temperature_range'] = df_m['temp_max'] - df_m['temp_min']
            df_m['temperature_squared'] = df_m['temperature'] ** 2
            df_m['location'] = loc_name
            df_m['latitude'] = loc_info["coords"][0]
            df_m['longitude'] = loc_info["coords"][1]
            df_m['bearing_from_source'] = calculate_bearing(loc_info["coords"][0], loc_info["coords"][1])
            fallback_records.append(df_m)

        return pd.concat(fallback_records, ignore_index=True), True


def fetch_historical_weather(locations):
    # Use the forecast endpoint with past_days instead of the archive (ERA5) API.
    # The ERA5 archive lags ~5 days, leaving the most recent calendar cells blank.
    # The forecast endpoint's past_days parameter returns blended NWP reanalysis with
    # no lag, ensuring the most recent days in the calendar are always populated.
    lats = [str(loc["coords"][0]) for loc in locations.values()]
    lons = [str(loc["coords"][1]) for loc in locations.values()]
    lat_param = ",".join(lats)
    lon_param = ",".join(lons)

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat_param}&longitude={lon_param}"
        f"&hourly=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,"
        f"wind_direction_10m,rain,shortwave_radiation,boundary_layer_height"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&past_days=31&forecast_days=1&timezone=America%2FChicago"
    )

    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        res_data = response.json()

        # Open-Meteo returns a list of dictionaries if multiple coordinates are requested
        forecast_list = res_data if isinstance(res_data, list) else [res_data]

        all_daily_records = []

        for idx, (loc_name, loc_info) in enumerate(locations.items()):
            loc_data = forecast_list[idx]
            hourly = loc_data.get("hourly", {})
            df_hourly = pd.DataFrame(hourly)
            df_hourly['time'] = pd.to_datetime(df_hourly['time'])
            df_hourly['date'] = df_hourly['time'].dt.strftime('%Y-%m-%d')

            # PBLH conversion (meters -> feet)
            if 'boundary_layer_height' in df_hourly.columns:
                df_hourly['boundary_layer_height_ft'] = df_hourly['boundary_layer_height'] * 3.28084
            else:
                df_hourly['boundary_layer_height_ft'] = 1500.0

            # Speed-weighted vector mean for wind direction — arithmetic mean of degrees
            # is invalid across the 0°/360° wrap (e.g. 350° and 10° average to 0°, not 180°).
            df_hourly['wind_u'] = df_hourly['wind_speed_10m'] * np.sin(np.radians(df_hourly['wind_direction_10m']))
            df_hourly['wind_v'] = df_hourly['wind_speed_10m'] * np.cos(np.radians(df_hourly['wind_direction_10m']))

            daily_df = df_hourly.groupby('date').agg({
                'temperature_2m': ['mean', 'min', 'max'],
                'rain': 'sum',
                'wind_speed_10m': 'mean',
                'wind_u': 'mean',
                'wind_v': 'mean',
                'relative_humidity_2m': 'mean',
                'surface_pressure': 'mean',
                'shortwave_radiation': 'mean',
                'boundary_layer_height_ft': 'mean'
            }).reset_index()

            daily_df.columns = [
                'date', 'temperature', 'temp_min', 'temp_max',
                'precipitation', 'wind_speed', 'wind_u', 'wind_v',
                'relative_humidity', 'atmospheric_pressure',
                'solar_radiation', 'boundary_layer_height'
            ]
            daily_df['wind_direction'] = np.degrees(np.arctan2(daily_df['wind_u'], daily_df['wind_v'])) % 360
            daily_df.drop(columns=['wind_u', 'wind_v'], inplace=True)

            daily_df['diurnal_temperature_range'] = daily_df['temp_max'] - daily_df['temp_min']
            daily_df['temperature_squared'] = daily_df['temperature'] ** 2
            daily_df['location'] = loc_name
            daily_df['latitude'] = loc_info["coords"][0]
            daily_df['longitude'] = loc_info["coords"][1]
            daily_df['bearing_from_source'] = calculate_bearing(loc_info["coords"][0], loc_info["coords"][1])
            daily_df['distance_from_source'] = calculate_distance(loc_info["coords"][0], loc_info["coords"][1])
            bearing_val = daily_df['bearing_from_source'].iloc[0]
            daily_df['wind_alignment'] = daily_df.apply(
                lambda r: compute_continuous_wind_alignment(r['wind_direction'], bearing_val), axis=1
            )

            all_daily_records.append(daily_df)

        combined_df = pd.concat(all_daily_records, ignore_index=True)
        # Keep only historical dates (past_days=31 + forecast_days=1 may include future rows)
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        combined_df = combined_df[combined_df['date'] <= today_str].copy()
        return combined_df, False

    except Exception:
        today = datetime.date.today()
        # Build clean simulated fallback dataframe
        dates = [(today - datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 31)]
        dates.reverse()
        fallback_records = []
        for loc_name, loc_info in locations.items():
            state_seed = int(hashlib.md5(loc_name.encode()).hexdigest()[:8], 16) % 10000
            np.random.seed(state_seed)
            temps = np.random.uniform(65.0, 85.0, 30)
            dtrs = np.random.uniform(10.0, 22.0, 30)
            winds = np.random.uniform(0.5, 6.0, 30)
            wind_dirs = np.random.uniform(0, 360, 30)
            rh = np.random.uniform(50.0, 85.0, 30)
            press = np.random.uniform(1008.0, 1018.0, 30)
            rad = np.random.uniform(100.0, 300.0, 30)
            blh = np.random.choice([400.0, 800.0, 1500.0, 2500.0], size=30, p=[0.15, 0.25, 0.40, 0.20])
            rain = np.random.choice([0.0, 0.05, 0.2], size=30, p=[0.75, 0.15, 0.10])

            mock_data = {
                'date': dates,
                'temperature': temps,
                'temp_min': temps - dtrs / 2.0,
                'temp_max': temps + dtrs / 2.0,
                'precipitation': rain,
                'wind_speed': winds,
                'wind_direction': wind_dirs,
                'relative_humidity': rh,
                'atmospheric_pressure': press,
                'solar_radiation': rad,
                'boundary_layer_height': blh
            }
            df_m = pd.DataFrame(mock_data)
            df_m['diurnal_temperature_range'] = df_m['temp_max'] - df_m['temp_min']
            df_m['temperature_squared'] = df_m['temperature'] ** 2
            df_m['location'] = loc_name
            df_m['latitude'] = loc_info["coords"][0]
            df_m['longitude'] = loc_info["coords"][1]
            df_m['bearing_from_source'] = calculate_bearing(loc_info["coords"][0], loc_info["coords"][1])
            fallback_records.append(df_m)

        return pd.concat(fallback_records, ignore_index=True), True
