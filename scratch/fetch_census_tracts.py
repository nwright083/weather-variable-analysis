"""Download and save US Census 2020 census tracts for 3 western KY counties."""
import requests, json, os, math, sys

# KY FIPS 21; Marshall=157, McCracken=145, Livingston=139
STATE = "21"
COUNTIES = ["157", "145", "139"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def try_tigerweb():
    """Try Census TIGERweb REST API."""
    url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer/6/query"
    params = {
        "where": f"STATEFP='{STATE}' AND COUNTYFP IN ({','.join(repr(c) for c in COUNTIES)})",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": 500,
    }
    print(f"Trying TIGERweb API...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    print(f"TIGERweb returned {len(features)} features")
    if features:
        print("Sample properties:", list(features[0]["properties"].keys()))
    return data, features

def try_census_cartographic():
    """Try Census Cartographic Boundary API for all KY tracts, then filter."""
    url = "https://raw.githubusercontent.com/uscensusbureau/citysdk/master/v2/GeoJSON/500k/2019/21/tract.json"
    print(f"Trying Census Cartographic Boundary API...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    print(f"Got {len(features)} total KY tracts, filtering to target counties...")
    # Filter to target counties
    filtered = []
    for f in features:
        props = f.get("properties", {})
        # Look for county FIPS field
        county_fp = props.get("COUNTYFP", props.get("county", props.get("COUNTY", "")))
        if str(county_fp) in COUNTIES:
            filtered.append(f)
    print(f"Filtered to {len(filtered)} tracts in target counties")
    return {"type": "FeatureCollection", "features": filtered}, filtered

def try_tigerweb_2022():
    """Try TIGERweb 2022 REST API with different layer."""
    url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Census2020/MapServer/10/query"
    # Marshall(157), McCracken(145), Livingston(139)
    where_clause = " OR ".join([
        f"(STATE='{STATE}' AND COUNTY='{c}')" for c in COUNTIES
    ])
    params = {
        "where": where_clause,
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": 500,
    }
    print(f"Trying TIGERweb 2022 API (layer 10)...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    print(f"TIGERweb 2022 returned {len(features)} features")
    if features:
        print("Sample properties:", list(features[0]["properties"].keys()))
    return data, features

def try_census_geocoder_tracts():
    """Use Census Bureau TIGERweb REST for Census Tracts layer."""
    # Try different approach using the feature service
    url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer/8/query"
    params = {
        "where": f"STATE='{STATE}' AND COUNTY IN ('157','145','139')",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": 500,
    }
    print(f"Trying TIGERweb Census2020 layer 8...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    print(f"Returned {len(features)} features")
    if features:
        print("Sample properties:", list(features[0]["properties"].keys()))
    return data, features

def try_shapefile():
    """Download and parse 2022 KY census tracts shapefile."""
    import urllib.request, zipfile, io, struct

    zip_url = "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_21_tract.zip"
    print(f"Downloading shapefile from {zip_url}...")
    req = urllib.request.urlopen(zip_url, timeout=120)
    zipdata = req.read()
    print(f"Downloaded {len(zipdata)} bytes")

    with zipfile.ZipFile(io.BytesIO(zipdata)) as zf:
        print("Files in zip:", zf.namelist())
        # Read .dbf for attributes
        dbf_name = [n for n in zf.namelist() if n.endswith('.dbf')][0]
        shp_name = [n for n in zf.namelist() if n.endswith('.shp')][0]
        dbf_data = zf.read(dbf_name)
        shp_data = zf.read(shp_name)

    # Parse DBF
    records = parse_dbf(dbf_data)
    # Parse SHP for centroids
    centroids = parse_shp_centroids(shp_data)

    print(f"Parsed {len(records)} DBF records")
    if records:
        print("DBF fields:", list(records[0].keys()))

    # Filter to target counties
    features = []
    for i, rec in enumerate(records):
        countyfp = str(rec.get('COUNTYFP', rec.get('COUNTY', ''))).strip()
        statefp = str(rec.get('STATEFP', rec.get('STATE', ''))).strip()
        if statefp == STATE and countyfp in COUNTIES:
            geoid = str(rec.get('GEOID', '')).strip()
            name = str(rec.get('NAME', '')).strip()
            intptlat = float(rec.get('INTPTLAT', 0))
            intptlon = float(rec.get('INTPTLON', 0))
            lat = intptlat if intptlat != 0 else (centroids[i][1] if i < len(centroids) else 0)
            lon = intptlon if intptlon != 0 else (centroids[i][0] if i < len(centroids) else 0)
            features.append({
                "type": "Feature",
                "properties": {
                    "GEOID": geoid,
                    "NAME": name,
                    "COUNTYFP": countyfp,
                    "STATEFP": statefp,
                    "INTPTLAT": intptlat,
                    "INTPTLON": intptlon,
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]}
            })

    print(f"Filtered to {len(features)} tracts in target counties")
    return {"type": "FeatureCollection", "features": features}, features

def parse_dbf(data):
    """Minimal DBF parser for census tract attributes."""
    import struct

    # DBF header
    num_records = struct.unpack_from('<I', data, 4)[0]
    header_size = struct.unpack_from('<H', data, 8)[0]
    record_size = struct.unpack_from('<H', data, 10)[0]

    # Parse field descriptors (each 32 bytes, starting at offset 32)
    fields = []
    offset = 32
    while offset < header_size - 1:
        if data[offset] == 0x0D:  # end of field list
            break
        name = data[offset:offset+11].decode('ascii', errors='replace').rstrip('\x00')
        ftype = chr(data[offset+11])
        length = data[offset+16]
        fields.append((name, ftype, length))
        offset += 32

    # Parse records
    records = []
    record_offset = header_size
    for i in range(num_records):
        if record_offset + record_size > len(data):
            break
        deletion_flag = data[record_offset]
        if deletion_flag == 0x2A:  # deleted record
            record_offset += record_size
            continue
        rec = {}
        field_offset = record_offset + 1  # skip deletion flag
        for fname, ftype, flength in fields:
            raw = data[field_offset:field_offset+flength].decode('ascii', errors='replace').strip()
            if ftype == 'N' or ftype == 'F':
                try:
                    rec[fname] = float(raw) if raw else 0.0
                except:
                    rec[fname] = raw
            else:
                rec[fname] = raw
            field_offset += flength
        records.append(rec)
        record_offset += record_size

    return records

def parse_shp_centroids(data):
    """Extract centroids from SHP polygons (bounding box midpoints as approximation)."""
    import struct

    centroids = []
    offset = 100  # skip file header

    while offset + 8 < len(data):
        try:
            # rec_num = struct.unpack_from('>I', data, offset)[0]
            content_length = struct.unpack_from('>I', data, offset + 4)[0] * 2
            shape_type = struct.unpack_from('<I', data, offset + 8)[0]

            if shape_type in (5, 15, 25):  # Polygon types
                # Bounding box: Xmin, Ymin, Xmax, Ymax
                xmin = struct.unpack_from('<d', data, offset + 12)[0]
                ymin = struct.unpack_from('<d', data, offset + 20)[0]
                xmax = struct.unpack_from('<d', data, offset + 28)[0]
                ymax = struct.unpack_from('<d', data, offset + 36)[0]
                centroids.append(((xmin + xmax) / 2, (ymin + ymax) / 2))
            else:
                centroids.append((0, 0))

            offset += 8 + content_length
        except struct.error:
            break

    return centroids

def build_locations_dict(features):
    """Print LOCATIONS dict for reference."""
    county_names = {"157": "Marshall", "145": "McCracken", "139": "Livingston"}

    entries = []
    for f in features:
        props = f.get("properties", {})
        geoid = props.get("GEOID", "")
        name = props.get("NAME", "")
        countyfp = props.get("COUNTYFP", "")
        county_name = county_names.get(str(countyfp).zfill(3), countyfp)

        # Get coordinates
        geom = f.get("geometry", {})
        if geom.get("type") == "Point":
            lon, lat = geom["coordinates"]
        elif geom.get("type") in ("Polygon", "MultiPolygon"):
            # Compute centroid from properties or geometry
            lat = float(props.get("INTPTLAT", 0))
            lon = float(props.get("INTPTLON", 0))
            if lat == 0:
                # Rough centroid from bounding box
                coords = geom["coordinates"]
                if geom["type"] == "Polygon":
                    ring = coords[0]
                else:
                    ring = coords[0][0]
                lons = [c[0] for c in ring]
                lats = [c[1] for c in ring]
                lon = sum(lons) / len(lons)
                lat = sum(lats) / len(lats)
        else:
            continue

        display = f"Tract {name}, {county_name} Co."
        entry = f'    "TRACT {geoid} ({display})": {{"coords": ({lat:.4f}, {lon:.4f})}},'
        entries.append((geoid, entry))

    entries.sort(key=lambda x: x[0])
    print("\n# LOCATIONS dict entries:")
    print("LOCATIONS = {")
    for _, e in entries:
        print(e)
    print("}")

    return entries

def save_geojson(data, features):
    """Save GeoJSON to calvert_tracts.geojson."""
    # If features have polygon geometry, keep as-is
    # If they only have point geometry, keep as-is
    out_path = os.path.join(ROOT, "calvert_tracts.geojson")

    # Standardize properties to include GEOID and display name
    county_names = {"157": "Marshall", "145": "McCracken", "139": "Livingston"}

    for f in features:
        props = f.get("properties", {})
        geoid = props.get("GEOID", props.get("GEOID10", ""))
        if not geoid:
            # Try to construct GEOID from STATE+COUNTY+TRACT
            state = props.get("STATE", props.get("STATEFP", "21"))
            county = props.get("COUNTY", props.get("COUNTYFP", ""))
            tract = props.get("TRACT", props.get("TRACTCE", ""))
            if county and tract:
                geoid = f"{state}{county.zfill(3)}{tract.zfill(6)}"
        props["GEOID"] = geoid

        name = props.get("NAME", props.get("NAMELSAD", ""))
        countyfp = str(props.get("COUNTYFP", props.get("COUNTY", ""))).zfill(3)
        county_name = county_names.get(countyfp, f"County {countyfp}")
        props["display_name"] = f"Tract {name}, {county_name} Co."

    out = {"type": "FeatureCollection", "features": features}
    with open(out_path, "w") as fh:
        json.dump(out, fh)
    print(f"\nSaved {len(features)} features to {out_path}")
    return out_path

def main():
    data, features = None, []

    # Try methods in order
    methods = [
        ("TIGERweb 2020", try_tigerweb),
        ("TIGERweb layer 8", try_census_geocoder_tracts),
        ("TIGERweb 2022 layer 10", try_tigerweb_2022),
        ("Census Cartographic Boundary", try_census_cartographic),
        ("Shapefile", try_shapefile),
    ]

    for name, method in methods:
        try:
            data, features = method()
            if features:
                print(f"SUCCESS with {name}: {len(features)} features")
                break
        except Exception as e:
            print(f"FAILED {name}: {e}")

    if not features:
        print("All methods failed!")
        sys.exit(1)

    # Save GeoJSON
    out_path = save_geojson(data, features)

    # Print LOCATIONS dict
    build_locations_dict(features)

    print(f"\nDone. GeoJSON saved to {out_path}")

if __name__ == "__main__":
    main()
