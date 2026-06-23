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

# Surrounding study locations mapped to ZIP Codes across Marshall, McCracken, and Livingston counties
LOCATIONS = {
    "ZIP 42029 (Calvert City)": {"coords": (37.0317, -88.3542)},
    "ZIP 42025 (Benton)": {"coords": (36.8576, -88.3506)},
    "ZIP 42045 (Grand Rivers)": {"coords": (37.0034, -88.2323)},
    "ZIP 42081 (Smithland)": {"coords": (37.1378, -88.3975)},
    "ZIP 42058 (Ledbetter)": {"coords": (37.0506, -88.4984)},
    "ZIP 42001 (Paducah)": {"coords": (37.0834, -88.6000)},
    "ZIP 42003 (Reidland)": {"coords": (37.0095, -88.5273)},
}

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


def predict_ori(row, coeffs, *, use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0, use_distance_decay=False, distance_decay_rate=0.0):
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
