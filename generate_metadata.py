import pandas as pd
import json

# Replace with your public health file path (CSV, XPT, SAS7BDAT, Excel, etc.)
DATA_FILE = "public_health_data.csv" 
df = pd.read_csv(DATA_FILE)

metadata = {
    "Total Rows": int(df.shape[0]),
    "Total Columns": int(df.shape[1]),
    "Column Structural Blueprint": []
}

for col in df.columns:
    col_info = {
        "Column Name": str(col),
        "Data Type": str(df[col].dtype),
        "Non-Null Count": int(df[col].notnull().sum()),
        "Missing Percentage": f"{(df[col].isnull().sum() / len(df) * 100):.2f}%",
        "Unique Values Count": int(df[col].nunique()),
    }
    
    # Safely pull numerical bounds or categorical options
    if pd.api.types.is_numeric_dtype(df[col]):
        col_info["Range"] = f"Min: {df[col].min()} to Max: {df[col].max()}"
    else:
        # Show top 3 categorical tags to map patterns
        col_info["Sample Categories"] = list(df[col].dropna().unique()[:3])
        
    metadata["Column Structural Blueprint"].append(col_info)

# Output directly to a lightweight JSON metadata mirror
with open("dataset_schema.json", "w") as f:
    json.dump(metadata, f, indent=4)

print("✅ Success: 'dataset_schema.json' generated safely for Cline.")
