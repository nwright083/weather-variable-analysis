import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PITT_CODE = """

# ==============================================================================
# SECTION 5: SPATIAL PROXIMITY & MULTI-SOURCE DISTANCE DECAY ANALYSIS
# ==============================================================================
print("\\n" + "="*80)
print("SECTION 5: SPATIAL PROXIMITY & MULTI-SOURCE DISTANCE DECAY ANALYSIS")
print("="*80)

# Emitters coordinates
emitters = {
    "Clairton": (40.2974, -79.8809),      # Clairton Coke Works
    "Edgar_Thomson": (40.3922, -79.8550), # Edgar Thomson Steel Works
    "Irvin_Works": (40.3644, -79.8944),   # Irvin Finishing Works
}

# 1. Parse GeoJSON centroids
geojson_path = 'Pittsburgh Data/pittsburgh_zips.geojson'
if not os.path.exists(geojson_path):
    geojson_path = 'pittsburgh_zips.geojson'

with open(geojson_path, 'r') as f:
    geojson_data = json.load(f)

centroids = {}
for feature in geojson_data['features']:
    props = feature['properties']
    zip_code = None
    for key in ['zip', 'zipcode', 'ZIPCODE', 'ZIP']:
        if key in props:
            zip_code = str(props[key])
            break
    if not zip_code:
        continue
    geom = feature['geometry']
    lats, lons = [], []
    if geom['type'] == 'Polygon':
        coords = geom['coordinates'][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
    elif geom['type'] == 'MultiPolygon':
        for poly in geom['coordinates']:
            coords = poly[0]
            lons.extend([c[0] for c in coords])
            lats.extend([c[1] for c in coords])
    if lats and lons:
        centroids[zip_code] = (np.mean(lats), np.mean(lons))

print(f"Loaded {len(centroids)} ZIP code centroids from GeoJSON.")

# 2. Map distances to ZIP codes
def haversine_dist(lat1, lon1, lat2, lon2):
    R = 3958.8  # miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

zip_distances = {name: {} for name in emitters.keys()}
for z, coords in centroids.items():
    for name, emit_coords in emitters.items():
        zip_distances[name][z] = haversine_dist(coords[0], coords[1], emit_coords[0], emit_coords[1])

# 3. Create Daily Panel Dataset
df_zipcode['zipcode'] = df_zipcode['zipcode'].astype(str)
df_panel = df_zipcode[df_zipcode['zipcode'].isin(centroids.keys())].copy()
for name in emitters.keys():
    df_panel[f'dist_{name}'] = df_panel['zipcode'].map(zip_distances[name])

agg_dict = {
    'complaints': 'sum',
    'temperature': ['mean', 'min', 'max'],
    'precipitation': 'sum',
    'wind_speed': 'mean',
    'relative_humidity': 'mean',
    'boundary_layer_height': 'mean',
    'atmospheric_pressure': 'mean',
    'solar_radiation': 'mean',
}
for name in emitters.keys():
    agg_dict[f'dist_{name}'] = 'first'

daily_zip = df_panel.groupby(['zipcode', 'date']).agg(agg_dict).reset_index()
flat_cols = ['zipcode', 'date', 'complaints', 'temperature', 'temp_min', 'temp_max',
             'precipitation', 'wind_speed', 'relative_humidity', 'boundary_layer_height',
             'atmospheric_pressure', 'solar_radiation']
for name in emitters.keys():
    flat_cols.append(f'dist_{name}')
daily_zip.columns = flat_cols
daily_zip['dtr'] = daily_zip['temp_max'] - daily_zip['temp_min']
daily_zip = daily_zip.dropna()

# Add exponential decay features (k=0.03 and k=0.02)
for name in emitters.keys():
    daily_zip[f'exp_03_{name}'] = np.exp(-0.03 * daily_zip[f'dist_{name}'])
    daily_zip[f'exp_02_{name}'] = np.exp(-0.02 * daily_zip[f'dist_{name}'])

print(f"Panel dataset generated: {len(daily_zip)} observations.")

# 4. Fit Panel OLS Regression
import statsmodels.api as sm
weather_vars_p = ['temperature', 'precipitation', 'wind_speed', 'relative_humidity',
                  'boundary_layer_height', 'atmospheric_pressure', 'solar_radiation', 'dtr']
exp_03_cols = [f'exp_03_{name}' for name in emitters.keys()]
exp_02_cols = [f'exp_02_{name}' for name in emitters.keys()]

# Model A: Weather Only
X_base = sm.add_constant(daily_zip[weather_vars_p])
res_base = sm.OLS(daily_zip['complaints'], X_base).fit()

# Model B: Weather + Multi-Source Exp-Decay (k=0.03)
X_spatial_03 = sm.add_constant(daily_zip[weather_vars_p + exp_03_cols])
res_spatial_03 = sm.OLS(daily_zip['complaints'], X_spatial_03).fit()

# Model C: Weather + Multi-Source Exp-Decay (k=0.02)
X_spatial_02 = sm.add_constant(daily_zip[weather_vars_p + exp_02_cols])
res_spatial_02 = sm.OLS(daily_zip['complaints'], X_spatial_02).fit()

print("\\n=== Model A (Weather-Only) R²: ", round(res_base.rsquared, 4))
print("=== Model B (Weather + Exp-Decay 0.03) R²: ", round(res_spatial_03.rsquared, 4))
print("=== Model C (Weather + Exp-Decay 0.02) R²: ", round(res_spatial_02.rsquared, 4))
print("\\n=== Model C (Weather + Exp-Decay 0.02) Regression Results ===")
print(res_spatial_02.summary())
"""

LOU_CODE = """

# ==============================================================================
# SECTION 5: SPATIAL PROXIMITY & MULTI-SOURCE DISTANCE DECAY ANALYSIS
# ==============================================================================
print("\\n" + "="*80)
print("SECTION 5: SPATIAL PROXIMITY & MULTI-SOURCE DISTANCE DECAY ANALYSIS")
print("="*80)

# Emitters coordinates
emitters = {
    "Rubbertown": (38.2195, -85.8450),    # Rubbertown Chemical Corridor
    "JBS_Swift_Butchertown": (38.2588, -85.7275), # JBS Swift Pork Processing Plant
}

# 1. Parse GeoJSON centroids
geojson_path = 'Louisville Data/louisville_zips.geojson'
if not os.path.exists(geojson_path):
    geojson_path = 'louisville_zips.geojson'

with open(geojson_path, 'r') as f:
    geojson_data = json.load(f)

centroids = {}
for feature in geojson_data['features']:
    props = feature['properties']
    zip_code = None
    for key in ['zip', 'zipcode', 'ZIPCODE', 'ZIP']:
        if key in props:
            zip_code = str(props[key])
            break
    if not zip_code:
        continue
    geom = feature['geometry']
    lats, lons = [], []
    if geom['type'] == 'Polygon':
        coords = geom['coordinates'][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
    elif geom['type'] == 'MultiPolygon':
        for poly in geom['coordinates']:
            coords = poly[0]
            lons.extend([c[0] for c in coords])
            lats.extend([c[1] for c in coords])
    if lats and lons:
        centroids[zip_code] = (np.mean(lats), np.mean(lons))

print(f"Loaded {len(centroids)} ZIP code centroids from GeoJSON.")

# 2. Map distances to ZIP codes
def haversine_dist(lat1, lon1, lat2, lon2):
    R = 3958.8  # miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

zip_distances = {name: {} for name in emitters.keys()}
for z, coords in centroids.items():
    for name, emit_coords in emitters.items():
        zip_distances[name][z] = haversine_dist(coords[0], coords[1], emit_coords[0], emit_coords[1])

# 3. Create Daily Panel Dataset
df_zipcode['zipcode'] = df_zipcode['zipcode'].astype(str)
df_panel = df_zipcode[df_zipcode['zipcode'].isin(centroids.keys())].copy()
for name in emitters.keys():
    df_panel[f'dist_{name}'] = df_panel['zipcode'].map(zip_distances[name])

agg_dict = {
    'complaints': 'sum',
    'temperature': ['mean', 'min', 'max'],
    'precipitation': 'sum',
    'wind_speed': 'mean',
    'relative_humidity': 'mean',
    'boundary_layer_height': 'mean',
    'atmospheric_pressure': 'mean',
    'solar_radiation': 'mean',
}
for name in emitters.keys():
    agg_dict[f'dist_{name}'] = 'first'

daily_zip = df_panel.groupby(['zipcode', 'date']).agg(agg_dict).reset_index()
flat_cols = ['zipcode', 'date', 'complaints', 'temperature', 'temp_min', 'temp_max',
             'precipitation', 'wind_speed', 'relative_humidity', 'boundary_layer_height',
             'atmospheric_pressure', 'solar_radiation']
for name in emitters.keys():
    flat_cols.append(f'dist_{name}')
daily_zip.columns = flat_cols
daily_zip['dtr'] = daily_zip['temp_max'] - daily_zip['temp_min']
daily_zip = daily_zip.dropna()

# Add exponential decay features (k=0.03 and k=0.02)
for name in emitters.keys():
    daily_zip[f'exp_03_{name}'] = np.exp(-0.03 * daily_zip[f'dist_{name}'])
    daily_zip[f'exp_02_{name}'] = np.exp(-0.02 * daily_zip[f'dist_{name}'])

print(f"Panel dataset generated: {len(daily_zip)} observations.")

# 4. Fit Panel OLS Regression
import statsmodels.api as sm
weather_vars_l = ['temperature', 'precipitation', 'wind_speed', 'relative_humidity',
                  'boundary_layer_height', 'atmospheric_pressure', 'solar_radiation', 'dtr']
exp_03_cols = [f'exp_03_{name}' for name in emitters.keys()]
exp_02_cols = [f'exp_02_{name}' for name in emitters.keys()]

# Model A: Weather Only
X_base = sm.add_constant(daily_zip[weather_vars_l])
res_base = sm.OLS(daily_zip['complaints'], X_base).fit()

# Model B: Weather + Multi-Source Exp-Decay (k=0.03)
X_spatial_03 = sm.add_constant(daily_zip[weather_vars_l + exp_03_cols])
res_spatial_03 = sm.OLS(daily_zip['complaints'], X_spatial_03).fit()

# Model C: Weather + Multi-Source Exp-Decay (k=0.02)
X_spatial_02 = sm.add_constant(daily_zip[weather_vars_l + exp_02_cols])
res_spatial_02 = sm.OLS(daily_zip['complaints'], X_spatial_02).fit()

print("\\n=== Model A (Weather-Only) R²: ", round(res_base.rsquared, 4))
print("=== Model B (Weather + Exp-Decay 0.03) R²: ", round(res_spatial_03.rsquared, 4))
print("=== Model C (Weather + Exp-Decay 0.02) R²: ", round(res_spatial_02.rsquared, 4))
print("\\n=== Model C (Weather + Exp-Decay 0.02) Regression Results ===")
print(res_spatial_02.summary())
"""

def update_py_file(file_path, code):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Locate Section 5 start
    marker = "# SECTION 5: SPATIAL PROXIMITY"
    if marker not in content:
        # Fall back to appending if not present
        print(f"Marker not found in {file_path}, appending instead...")
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(code)
        return

    # Truncate at the marker start (which is preceded by the comments and line of = )
    idx = content.find(marker)
    # Move back to the beginning of the header block line: # ========================================
    block_start = content.rfind("# ===", 0, idx)
    if block_start == -1:
        block_start = idx
        
    truncated_content = content[:block_start].rstrip() + "\n"
    
    print(f"Updating spatial analysis in {file_path}...")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(truncated_content + code)

def update_notebook(file_path, code):
    if not os.path.exists(file_path):
        print(f"Notebook not found: {file_path}")
        return
    with open(file_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
        
    # Filter out cells containing the Section 5 content
    filtered_cells = []
    for cell in nb.get('cells', []):
        source_str = "".join(cell.get('source', []))
        if "SECTION 5: SPATIAL PROXIMITY" in source_str or "Model B (Weather + Exp-Decay 0.03)" in source_str:
            continue
        filtered_cells.append(cell)
        
    nb['cells'] = filtered_cells
    
    print(f"Appending updated spatial analysis cells to {file_path}...")
    # Create markdown header cell
    md_cell = {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "# SECTION 5: SPATIAL PROXIMITY & MULTI-SOURCE DISTANCE DECAY ANALYSIS\\n",
            "This section evaluates whether incorporating the distance from multiple industrial emitters into our models improves the overall fit and explanatory power of the odor risk regression specs. We compare exponential decay rates of both $k = 0.03$ and $k = 0.02$."
        ]
    }
    
    # Create code cell
    code_lines = [line + "\n" for line in code.strip().split("\n")]
    if code_lines:
        code_lines[-1] = code_lines[-1].rstrip("\n")
        
    code_cell = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": code_lines
    }
    
    nb['cells'].append(md_cell)
    nb['cells'].append(code_cell)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1)

def main():
    # 1. Update Pittsburgh files
    update_py_file("Pittsburgh Data/Odor_Complaint_Analysis_v2.py", PITT_CODE)
    update_py_file("Pittsburgh Data/Odor_Complaint_Analysis_v2_debiased.py", PITT_CODE)
    update_notebook("Pittsburgh Data/Odor_Complaint_Analysis_v2.ipynb", PITT_CODE)
    update_notebook("Pittsburgh Data/Odor_Complaint_Analysis_v2_debiased.ipynb", PITT_CODE)

    # 2. Update Louisville files
    update_py_file("Louisville Data/Odor_Complaint_Analysis_v2.py", LOU_CODE)
    update_py_file("Louisville Data/Odor_Complaint_Analysis_v2_debiased.py", LOU_CODE)
    update_notebook("Louisville Data/Odor_Complaint_Analysis_v2.ipynb", LOU_CODE)
    update_notebook("Louisville Data/Odor_Complaint_Analysis_v2_debiased.ipynb", LOU_CODE)

if __name__ == "__main__":
    main()
