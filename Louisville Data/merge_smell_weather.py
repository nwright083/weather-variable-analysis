import pandas as pd
import numpy as np

# 1. Load Data
import os
if os.path.exists("Louisville Data"):
    weather_file = "Louisville Data/open-meteo-complete_hourly.csv"
    smell_file = "Louisville Data/smell_reports.csv"
    output_file = "Louisville Data/open-meteo-smell-merged.csv"
elif os.path.exists("open-meteo-complete_hourly.csv"):
    weather_file = "open-meteo-complete_hourly.csv"
    smell_file = "smell_reports.csv"
    output_file = "open-meteo-smell-merged.csv"
else:
    weather_file = "Data/open-meteo-complete_hourly.csv"
    smell_file = "Data/smell_reports.csv"
    output_file = "Data/open-meteo-smell-merged.csv"

print(f"Loading weather data from {weather_file}...")
weather_df = pd.read_csv(weather_file)
print(f"Loading smell reports from {smell_file}...")
smell_df = pd.read_csv(smell_file)

# 2. Process DateTime
print("Converting weather data timestamps from UTC to America/Kentucky/Louisville local time...")
weather_df['datetime_utc'] = pd.to_datetime(weather_df['time'], utc=True)
weather_df['datetime_local'] = weather_df['datetime_utc'].dt.tz_convert('America/Kentucky/Louisville')
weather_df['time'] = weather_df['datetime_local'].dt.tz_localize(None).dt.strftime('%Y-%m-%dT%H:%M')

print("Processing smell reports timestamps...")
# Convert date & time to a timezone-aware datetime
smell_df['datetime_aware'] = pd.to_datetime(smell_df['date & time'], utc=True)

# Convert to Local Time (Louisville, KY is in Eastern Time)
smell_df['datetime_local'] = smell_df['datetime_aware'].dt.tz_convert('America/Kentucky/Louisville')

# Floor to the nearest hour, remove timezone, and format to match weather data "YYYY-MM-DDTHH:MM"
smell_df['time'] = smell_df['datetime_local'].dt.tz_localize(None).dt.floor('h').dt.strftime('%Y-%m-%dT%H:%M')

# Clean zipcodes to ensure matching (avoid ".0" floats)
def clean_zip(z):
    try:
        # Convert to float then int to handle floats like 40202.0, then string
        if pd.isna(z):
            return "unknown"
        return str(int(float(z)))
    except:
        return str(z)

print("Standardizing zipcodes...")
weather_df['zipcode'] = weather_df['zipcode'].apply(clean_zip)
smell_df['zipcode'] = smell_df['zipcode'].apply(clean_zip)

print("Deduplicating weather observations based on local time and zipcode...")
weather_df = weather_df.drop_duplicates(subset=['zipcode', 'time'])

# 3. Aggregate Smell Reports
print("Aggregating smell reports by zipcode and hour...")

def concat_unique_strings(series):
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals != '']
    if len(vals) == 0:
        return ""
    # Maintain order and get unique strings
    unique_vals = list(dict.fromkeys(vals))
    return " | ".join(unique_vals)

smell_agg = smell_df.groupby(['zipcode', 'time']).agg(
    smell_report_count=('smell value', 'size'),
    smell_value_average=('smell value', 'mean'),
    smell_value_max=('smell value', 'max'),
    smell_descriptions=('smell description', concat_unique_strings),
    smell_symptoms=('symptoms', concat_unique_strings),
    smell_comments=('additional comments', concat_unique_strings)
).reset_index()

# 4. Merge Data
print("Merging weather data and smell reports (Left Join)...")
merged_df = weather_df.merge(smell_agg, on=['zipcode', 'time'], how='left')

# Fill NA for counts (if no smell report, count is 0)
merged_df['smell_report_count'] = merged_df['smell_report_count'].fillna(0).astype(int)

# Fill empty strings for text columns
for col in ['smell_descriptions', 'smell_symptoms', 'smell_comments']:
    merged_df[col] = merged_df[col].fillna("")

# Perform robust weather variable imputation
def impute_weather_columns(df):
    print("Performing robust weather variable imputation...")
    weather_cols = [
        'temperature_2m (°F)', 'relative_humidity_2m (%)', 'dew_point_2m (°F)',
        'surface_pressure (hPa)', 'wind_speed_10m (mp/h)', 'wind_direction_10m (°)',
        'rain (inch)', 'direct_radiation (W/m²)', 'direct_normal_irradiance (W/m²)',
        'vapour_pressure_deficit (kPa)', 'sunshine_duration (s)',
        'boundary_layer_height (ft)', 'shortwave_radiation (W/m²)'
    ]
    weather_cols = [c for c in weather_cols if c in df.columns]
    
    # Parse temporary datetime columns for grouping
    parsed_dt = pd.to_datetime(df['time'])
    df['_month'] = parsed_dt.dt.month
    df['_hour'] = parsed_dt.dt.hour
    
    for col in weather_cols:
        null_count = df[col].isnull().sum()
        if null_count == 0:
            continue
            
        print(f"  Imputing {col} ({null_count} nulls)...")
        
        # Step 1: Linear interpolation for small gaps (max 6 consecutive hours)
        df[col] = df.groupby('zipcode', group_keys=False)[col].apply(
            lambda x: x.interpolate(method='linear', limit=6)
        )
        
        # Check remaining
        rem_nulls = df[col].isnull().sum()
        if rem_nulls > 0:
            # Step 2: Impute using zipcode-month-hour historical median
            zip_month_hour_median = df.groupby(['zipcode', '_month', '_hour'])[col].transform('median')
            df[col] = df[col].fillna(zip_month_hour_median)
            rem_nulls = df[col].isnull().sum()
            
        if rem_nulls > 0:
            # Step 3: Fallback to month-hour historical median (city-wide)
            month_hour_median = df.groupby(['_month', '_hour'])[col].transform('median')
            df[col] = df[col].fillna(month_hour_median)
            rem_nulls = df[col].isnull().sum()
            
        if rem_nulls > 0:
            # Step 4: Fallback to overall median
            overall_median = df[col].median()
            df[col] = df[col].fillna(overall_median)
            
        print(f"  Completed {col}. Remaining nulls: {df[col].isnull().sum()}")
            
    df.drop(columns=['_month', '_hour'], inplace=True)
    return df

merged_df = impute_weather_columns(merged_df)

# 5. Save output
print(f"Saving merged data to {output_file}...")
merged_df.to_csv(output_file, index=False)

# Quick stats
total_smell_reports_in_original = len(smell_df)
hours_with_smells = len(smell_agg)
hours_matched_in_weather = merged_df['smell_report_count'].sum()

print("\n--- Summary ---")
print(f"Total rows in final merged dataset: {len(merged_df)}")
print(f"Total raw smell reports processed: {total_smell_reports_in_original}")
print(f"Total unique hour-zipcode combinations with smells: {hours_with_smells}")
print(f"Total smell reports successfully matched to weather data: {hours_matched_in_weather}")
