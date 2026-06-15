import pandas as pd

# Load the file using the dynamic boundary parser we created
def get_clean_df(filepath):
    skiprows = 0
    nrows = None
    with open(filepath, 'r') as f:
        for idx, line in enumerate(f):
            if line.startswith("location_id,time"):
                skiprows = idx
                break
        for idx, line in enumerate(f, start=skiprows + 1):
            if line.strip() == "":
                nrows = idx - skiprows - 1
                break
                
    # Read the locations metadata table (7 columns) at the top of the file
    locations_df = pd.read_csv(filepath, nrows=skiprows - 2)
    
    # Coordinates-to-zipcode mapping verified via OpenStreetMap Nominatim
    zip_mapping = {
        (38.27768, -85.743225): '47130',
        (38.20738, -85.74899): '40292',
        (38.20738, -85.62753): '40220',
        (38.27768, -85.62161): '40222',
        (38.13708, -85.75473): '40214',
        (38.20738, -85.87045): '40216',
        (38.13708, -85.63342): '40228',
        (38.27768, -85.5): '40245',
        (38.20738, -85.38461): '40067',
        (38.13708, -85.87601): '40258',
        (38.066784, -85.88156): '40272',
        (38.13708, -85.512146): '40299',
        (38.20738, -85.50607): '40243',
    }
    coords_zip = { (round(lat, 6), round(lon, 6)): zip_code for (lat, lon), zip_code in zip_mapping.items() }
    
    # Map zip code to each location
    locations_df['zipcode'] = locations_df.apply(
        lambda r: coords_zip.get((round(r['latitude'], 6), round(r['longitude'], 6))), 
        axis=1
    )
    
    # Read the hourly weather records table (15 columns)
    hourly_df = pd.read_csv(filepath, skiprows=skiprows, nrows=nrows)
    
    # Merge latitude, longitude, and zipcode columns from locations metadata
    merged_df = hourly_df.merge(
        locations_df[['location_id', 'latitude', 'longitude', 'zipcode']], 
        on='location_id', 
        how='left'
    )
    
    # Reorder columns to place latitude, longitude, and zipcode immediately after location_id
    cols = list(merged_df.columns)
    cols.insert(1, cols.pop(cols.index('latitude')))
    cols.insert(2, cols.pop(cols.index('longitude')))
    cols.insert(3, cols.pop(cols.index('zipcode')))
    
    return merged_df[cols]

# Export clean version of num_1
df_1 = get_clean_df("Data/open-meteo-num_1.csv")
df_1.to_csv("Data/open-meteo-num_1_hourly_clean.csv", index=False)

# Export clean version of num_2
df_2 = get_clean_df("Data/open-meteo-num_2.csv")
df_2.to_csv("Data/open-meteo-num_2_hourly_clean.csv", index=False)

print("Saved clean CSVs!")
