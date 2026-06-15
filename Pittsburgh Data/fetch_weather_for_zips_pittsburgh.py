import pandas as pd
import numpy as np
import urllib.request
import json
import ssl
import time
import os
import shutil

# 1. Load Smell Reports to extract zipcodes and coordinate proxies
smell_file = "Pittsburgh Data/smell_reports_pittsburgh.csv"
print(f"Loading smell reports from {smell_file}...", flush=True)
smell_df = pd.read_csv(smell_file)

# Standardize zipcode
def clean_zip(z):
    try:
        if pd.isna(z): return "unknown"
        return str(int(float(z)))
    except:
        return str(z)

smell_df['zipcode'] = smell_df['zipcode'].apply(clean_zip)

# Drop rows with unknown zipcodes or missing coordinates
smell_df = smell_df[(smell_df['zipcode'] != "unknown") & (smell_df['skewed latitude'].notna()) & (smell_df['skewed longitude'].notna())]

# Group by zipcode to get mean coordinates
zip_coords = smell_df.groupby('zipcode').agg(
    latitude=('skewed latitude', 'mean'),
    longitude=('skewed longitude', 'mean'),
    count=('smell value', 'size')
).reset_index().sort_values('count', ascending=False)

print(f"Found {len(zip_coords)} unique zipcodes with valid coordinates.", flush=True)

# Create a temp folder for saving zipcode weather data
temp_dir = "Pittsburgh Data/temp_weather"
os.makedirs(temp_dir, exist_ok=True)
print(f"Created/verified temporary folder: {temp_dir}", flush=True)

# Identify which zip codes we still need to download
zip_coords['temp_file'] = zip_coords['zipcode'].apply(lambda z: os.path.join(temp_dir, f"{z}.csv"))
needed_zips = zip_coords[~zip_coords['temp_file'].apply(os.path.exists)].copy()

print(f"Skipping {len(zip_coords) - len(needed_zips)} zipcodes already downloaded.")
print(f"Need to download {len(needed_zips)} zipcodes.")

# 2. Setup Open-Meteo API request parameters
start_date = "2018-01-01"
end_date = "2025-12-31"  # Truncated to the exact smell reports range to save API bandwidth
variables = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure",
    "wind_speed_10m", "wind_direction_10m", "rain", "vapour_pressure_deficit",
    "sunshine_duration", "boundary_layer_height", "shortwave_radiation"
]
variables_str = ",".join(variables)

ssl_context = ssl._create_unverified_context()

# Map API return columns to target CSV schema
column_mapping = {
    'temperature_2m': 'temperature_2m (°F)',
    'relative_humidity_2m': 'relative_humidity_2m (%)',
    'dew_point_2m': 'dew_point_2m (°F)',
    'surface_pressure': 'surface_pressure (hPa)',
    'wind_speed_10m': 'wind_speed_10m (mp/h)',
    'wind_direction_10m': 'wind_direction_10m (°)',
    'rain': 'rain (inch)',
    'direct_radiation': 'direct_radiation (W/m²)',
    'direct_normal_irradiance': 'direct_normal_irradiance (W/m²)',
    'vapour_pressure_deficit': 'vapour_pressure_deficit (kPa)',
    'sunshine_duration': 'sunshine_duration (s)',
    'boundary_layer_height': 'boundary_layer_height (ft)',
    'shortwave_radiation': 'shortwave_radiation (W/m²)'
}

if len(needed_zips) > 0:
    needed_zips['location_id'] = range(10 + len(zip_coords) - len(needed_zips), 10 + len(zip_coords))

    print(f"\n--- Starting weather data fetch from Open-Meteo for {len(needed_zips)} zipcodes ---", flush=True)

    for idx, row in needed_zips.iterrows():
        zipcode = row['zipcode']
        lat = row['latitude']
        lon = row['longitude']
        loc_id = row['location_id']
        count = row['count']
        
        temp_file = os.path.join(temp_dir, f"{zipcode}.csv")
        
        print(f"Fetching weather for Zip {zipcode} ({count} reports) | Lat: {lat:.5f}, Lon: {lon:.5f} | loc_id: {loc_id}...", flush=True)
        
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat:.5f}&longitude={lon:.5f}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&hourly={variables_str}"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        )
        
        success = False
        retries = 5
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ssl_context, timeout=15) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    
                hourly_data = data.get("hourly", {})
                if not hourly_data:
                    raise ValueError("No 'hourly' data found in response")
                    
                # Convert to DataFrame
                df_loc = pd.DataFrame(hourly_data)
                
                # Map metadata columns
                df_loc['location_id'] = loc_id
                df_loc['latitude'] = lat
                df_loc['longitude'] = lon
                df_loc['zipcode'] = zipcode
                
                # Unit conversions (boundary_layer_height meters -> feet)
                if 'boundary_layer_height' in df_loc.columns:
                    df_loc['boundary_layer_height'] = df_loc['boundary_layer_height'] * 3.28084
                    
                # Rename columns
                df_loc = df_loc.rename(columns=column_mapping)
                
                # Reorder columns to match original complete dataset
                cols = [
                    'location_id', 'latitude', 'longitude', 'zipcode', 'time',
                    'temperature_2m (°F)', 'relative_humidity_2m (%)', 'dew_point_2m (°F)',
                    'surface_pressure (hPa)', 'wind_speed_10m (mp/h)', 'wind_direction_10m (°)',
                    'rain (inch)', 'direct_radiation (W/m²)', 'direct_normal_irradiance (W/m²)',
                    'vapour_pressure_deficit (kPa)', 'sunshine_duration (s)',
                    'boundary_layer_height (ft)', 'shortwave_radiation (W/m²)'
                ]
                
                # Ensure all columns exist, fill missing with NaN if any
                for c in cols:
                    if c not in df_loc.columns:
                        df_loc[c] = np.nan
                
                df_loc = df_loc[cols]
                
                # Save to temporary file
                df_loc.to_csv(temp_file, index=False)
                print(f"  Successfully saved Zip {zipcode} data to temp file.", flush=True)
                success = True
                break
            except Exception as e:
                if "429" in str(e):
                    import datetime
                    now = datetime.datetime.now()
                    sleep_secs = 3600 - (now.minute * 60 + now.second) + 15
                    print(f"  [429 Rate Limit] Exceeded hourly limit. Sleeping for {sleep_secs} seconds until the next hour...", flush=True)
                    time.sleep(sleep_secs)
                else:
                    backoff_sleep = [15, 30, 60, 120, 240][attempt]
                    print(f"  [Attempt {attempt+1}/{retries}] Error fetching Zip {zipcode}: {e}. Sleeping {backoff_sleep}s...", flush=True)
                    time.sleep(backoff_sleep)
                
        if not success:
            print(f"  Failed to fetch data for Zip {zipcode} after {retries} attempts.", flush=True)
            
        # Politeness delay of 165.0 seconds to prevent getting rate-limited (stays under the 5,000 hourly API weight limit)
        time.sleep(165.0)

# 3. Concatenate all downloaded data
all_weather_dfs = []
print("\n--- Combining all zipcode weather data ---", flush=True)
for zipcode in zip_coords['zipcode']:
    temp_file = os.path.join(temp_dir, f"{zipcode}.csv")
    if os.path.exists(temp_file):
        try:
            df_zip = pd.read_csv(temp_file)
            all_weather_dfs.append(df_zip)
        except Exception as e:
            print(f"Error reading {temp_file}: {e}", flush=True)

if all_weather_dfs:
    combined_weather = pd.concat(all_weather_dfs, ignore_index=True)
    output_file = "Pittsburgh Data/open-meteo-complete_hourly.csv"
    print(f"\nSaving combined weather dataset to {output_file}...", flush=True)
    combined_weather.to_csv(output_file, index=False)
    print(f"Successfully saved {len(combined_weather)} rows of weather data!", flush=True)
    
    # Clean up temp folder
    print(f"Cleaning up temporary folder: {temp_dir}...", flush=True)
    try:
        shutil.rmtree(temp_dir)
        print("Cleanup complete.", flush=True)
    except Exception as e:
        print(f"Error during cleanup: {e}", flush=True)
else:
    print("No weather data was combined.", flush=True)
