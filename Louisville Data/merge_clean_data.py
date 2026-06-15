import pandas as pd

# Load the cleaned hourly datasets
file_1 = "Data/open-meteo-num_1_hourly_clean.csv"
file_2 = "Data/open-meteo-num_2_hourly_clean.csv"

print("Loading cleaned datasets...")
df_1 = pd.read_csv(file_1)
df_2 = pd.read_csv(file_2)

print(f"Loaded {file_1}: {len(df_1)} rows")
print(f"Loaded {file_2}: {len(df_2)} rows")

# Concatenate the clean dataframes
print("Concatenating datasets...")
combined_df = pd.concat([df_1, df_2], ignore_index=True)

# Deduplicate based on latitude, longitude, and timestamp
initial_rows = len(combined_df)
combined_df = combined_df.drop_duplicates(subset=['latitude', 'longitude', 'time'])
final_rows = len(combined_df)
print(f"Deduplication complete: Removed {initial_rows - final_rows} duplicate rows across files.")

# Generate globally consistent location IDs based on unique coordinates
unique_coords = combined_df[['latitude', 'longitude', 'zipcode']].drop_duplicates().sort_values(['latitude', 'longitude']).reset_index(drop=True)
unique_coords['new_location_id'] = unique_coords.index

print(f"Total unique locations in combined dataset: {len(unique_coords)}")
print(unique_coords)

# Merge the new global location IDs back and clean up columns
combined_df = combined_df.merge(unique_coords, on=['latitude', 'longitude', 'zipcode'], how='left')
combined_df = combined_df.drop(columns=['location_id']).rename(columns={'new_location_id': 'location_id'})

# Ensure location_id is the first column
cols = list(combined_df.columns)
cols.insert(0, cols.pop(cols.index('location_id')))
combined_df = combined_df[cols]

# Save the complete file
output_file = "Data/open-meteo-complete_hourly.csv"
combined_df.to_csv(output_file, index=False)
print(f"Saved complete merged CSV to '{output_file}' with {len(combined_df)} rows!")
