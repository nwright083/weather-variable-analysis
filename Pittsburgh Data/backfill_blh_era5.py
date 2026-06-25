"""
Backfill real ERA5 boundary-layer-height data for Jan–Jun 2024
into open-meteo-complete_hourly.csv.

The raw CSV is 100% null for 'boundary_layer_height (ft)' in
2024-01-01 00:00 → 2024-06-30 23:00 across all 61 Pittsburgh zip
locations.  Open-Meteo cannot supply that window; this script
fetches it from the Copernicus CDS ERA5 reanalysis.

Usage:
    .venv/bin/python "Pittsburgh Data/backfill_blh_era5.py"

Prerequisites:
    ~/.cdsapirc  with valid key (owner-read-only)
    pip install cdsapi xarray netcdf4  (already done)

Outputs (all in SCRATCHPAD, never in the repo):
    era5_blh_2024_h1.nc          raw NetCDF from CDS
    era5_blh_2024_h1_tidy.csv    tidy [location_id, time, blh_ft]

In-place modification:
    open-meteo-complete_hourly.csv   null BLH rows filled with ERA5 values
    open-meteo-complete_hourly.bak.csv  backup in SCRATCHPAD
"""

import os
import sys
import io
import shutil
import pandas as pd
import numpy as np
import cdsapi
import xarray as xr

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_CSV = os.path.join(HERE, "open-meteo-complete_hourly.csv")

SCRATCHPAD = (
    "/private/tmp/claude-501/-Users-nawrig04-weather-varaible-analysis"
    "/34f6a295-e631-4c02-89e3-f2f6ab99783d/scratchpad"
)
os.makedirs(SCRATCHPAD, exist_ok=True)

NC_PATH    = os.path.join(SCRATCHPAD, "era5_blh_2024_h1.nc")
TIDY_CSV   = os.path.join(SCRATCHPAD, "era5_blh_2024_h1_tidy.csv")
BACKUP_CSV = os.path.join(SCRATCHPAD, "open-meteo-complete_hourly.bak.csv")

BLH_COL = "boundary_layer_height (ft)"
TIME_COL = "time"
LOC_COL  = "location_id"

# H1-2024 window (inclusive on both sides)
WINDOW_START = "2024-01-01T00:00"
WINDOW_END   = "2024-06-30T23:00"

# Bounding box for all 61 Pittsburgh zip centroids (+0.25° pad)
# Lat 40.29–40.64 → N=40.90, S=40.04
# Lon -80.18 to -79.72 → W=-80.44, E=-79.47
AREA = [40.90, -80.44, 40.04, -79.47]   # [N, W, S, E]

# ---------------------------------------------------------------------------
# Step A2 — Fetch ERA5 BLH from CDS
# ---------------------------------------------------------------------------

def fetch_era5_blh():
    if os.path.exists(NC_PATH):
        print(f"[A2] NetCDF already exists at {NC_PATH} — skipping CDS download.")
        return
    print("[A2] Fetching ERA5 BLH from Copernicus CDS …")
    print("     (This request is queued on the CDS server; may take a few minutes.)")
    c = cdsapi.Client()
    c.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": ["reanalysis"],
            "variable": ["boundary_layer_height"],
            "year": ["2024"],
            "month": ["01", "02", "03", "04", "05", "06"],
            "day":   [f"{d:02d}" for d in range(1, 32)],
            "time":  [f"{h:02d}:00" for h in range(24)],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": AREA,
        },
        NC_PATH,
    )
    print(f"[A2] Saved to {NC_PATH}")


# ---------------------------------------------------------------------------
# Step A2b — Build tidy CSV [location_id, time, blh_ft]
# ---------------------------------------------------------------------------

def build_tidy_csv():
    if os.path.exists(TIDY_CSV):
        print(f"[A2b] Tidy CSV already exists at {TIDY_CSV} — skipping rebuild.")
        return

    print("[A2b] Building tidy CSV from NetCDF …")

    # Load ERA5 dataset
    ds = xr.open_dataset(NC_PATH)

    # ERA5 BLH variable is typically 'blh' in the NetCDF
    blh_var = None
    for candidate in ("blh", "boundary_layer_height", "BLH"):
        if candidate in ds:
            blh_var = candidate
            break
    if blh_var is None:
        print(f"[ERROR] Variables in NetCDF: {list(ds.data_vars)}")
        raise KeyError("Cannot find BLH variable in ERA5 NetCDF. Check variable list above.")

    print(f"         ERA5 variable: '{blh_var}'")
    print(f"         ERA5 grid: lat {float(ds.latitude.min()):.2f}–{float(ds.latitude.max()):.2f}, "
          f"lon {float(ds.longitude.min()):.2f}–{float(ds.longitude.max()):.2f}")
    print(f"         Time steps: {len(ds.valid_time)}")

    # Read location coordinates from raw CSV (just the first row per location)
    locs = (
        pd.read_csv(RAW_CSV, usecols=[LOC_COL, "latitude", "longitude"])
        .drop_duplicates(LOC_COL)
        .reset_index(drop=True)
    )
    print(f"         Locations: {len(locs)}")

    rows = []
    for _, loc in locs.iterrows():
        loc_id = int(loc[LOC_COL])
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])

        # Extract nearest ERA5 cell for this location
        blh_series = (
            ds[blh_var]
            .sel(latitude=lat, longitude=lon, method="nearest")
            .values
            .flatten()   # shape (n_times,)
        )

        # Build time index — use valid_time if present, else time
        time_var = "valid_time" if "valid_time" in ds else "time"
        times = pd.to_datetime(ds[time_var].values)

        for t, blh_m in zip(times, blh_series):
            # ERA5 is UTC; format to match CSV time strings 'YYYY-MM-DDTHH:MM'
            t_str = t.strftime("%Y-%m-%dT%H:%M")
            blh_ft = float(blh_m) * 3.28084   # meters → feet
            rows.append((loc_id, t_str, blh_ft))

    tidy = pd.DataFrame(rows, columns=[LOC_COL, TIME_COL, "blh_ft"])
    tidy.to_csv(TIDY_CSV, index=False)
    print(f"[A2b] Tidy CSV written: {len(tidy):,} rows → {TIDY_CSV}")

    # Sanity: check diurnal variation for one location/day
    sample = tidy[(tidy[LOC_COL] == 10) & (tidy[TIME_COL].str.startswith("2024-03-15"))]
    if not sample.empty:
        print(f"         Sanity (loc_id=10, 2024-03-15): "
              f"min={sample.blh_ft.min():.0f} ft  max={sample.blh_ft.max():.0f} ft  "
              f"(should show diurnal variation)")


# ---------------------------------------------------------------------------
# Step A3 — Patch the raw hourly CSV in place
# ---------------------------------------------------------------------------

def patch_raw_csv():
    print("[A3] Patching open-meteo-complete_hourly.csv …")

    # Load tidy ERA5 data
    era5 = pd.read_csv(TIDY_CSV)
    era5_lookup = era5.set_index([LOC_COL, TIME_COL])["blh_ft"]
    print(f"     ERA5 lookup size: {len(era5_lookup):,} rows")

    # Backup
    if not os.path.exists(BACKUP_CSV):
        print(f"     Backing up to {BACKUP_CSV} …")
        shutil.copy2(RAW_CSV, BACKUP_CSV)
        print("     Backup done.")
    else:
        print(f"     Backup already exists at {BACKUP_CSV}")

    # Process in chunks; only touch H1-2024 null rows
    chunk_size = 100_000
    chunks_out = []
    total_filled = 0
    total_rows = 0

    for chunk in pd.read_csv(RAW_CSV, chunksize=chunk_size):
        total_rows += len(chunk)
        # Identify rows in the window with null BLH
        in_window = (chunk[TIME_COL] >= WINDOW_START) & (chunk[TIME_COL] <= WINDOW_END)
        null_blh  = chunk[BLH_COL].isna()
        to_fill   = in_window & null_blh

        if to_fill.any():
            # Build a MultiIndex for the lookup
            keys = list(zip(chunk.loc[to_fill, LOC_COL].astype(int),
                            chunk.loc[to_fill, TIME_COL]))
            filled = era5_lookup.reindex(keys).values
            chunk.loc[to_fill, BLH_COL] = filled
            n_filled = int(to_fill.sum()) - int(pd.isna(filled).sum())
            total_filled += n_filled

        chunks_out.append(chunk)

    print(f"     Processed {total_rows:,} rows; filled {total_filled:,} null BLH values.")

    # Write patched file
    print("     Writing patched CSV (this may take ~1–2 min for 567 MB) …")
    out_chunks = iter(chunks_out)
    first = next(out_chunks)
    first.to_csv(RAW_CSV, index=False)
    with open(RAW_CSV, "a") as f:
        for ch in out_chunks:
            ch.to_csv(f, index=False, header=False)
    print("     Patched file written.")


# ---------------------------------------------------------------------------
# Step A3b — Verify
# ---------------------------------------------------------------------------

def verify_patch():
    print("[A3b] Verifying patch …")
    sample = []
    null_count = 0
    total_window = 0
    for chunk in pd.read_csv(RAW_CSV, usecols=[LOC_COL, TIME_COL, BLH_COL],
                              chunksize=200_000):
        mask = (chunk[TIME_COL] >= WINDOW_START) & (chunk[TIME_COL] <= WINDOW_END)
        sub = chunk[mask]
        total_window += len(sub)
        null_count   += int(sub[BLH_COL].isna().sum())
        if len(sample) < 24:
            s10 = sub[sub[LOC_COL] == 10]
            if not s10.empty:
                sample.extend(s10.head(24 - len(sample)).to_dict("records"))

    pct_null = 100.0 * null_count / total_window if total_window else 0
    print(f"     Window rows: {total_window:,} | Null BLH: {null_count:,} ({pct_null:.2f}%)")
    if sample:
        blhs = [r[BLH_COL] for r in sample[:6]]
        print(f"     Sample BLH values (loc_id=10, first 6 hours): "
              f"{[f'{v:.0f}' for v in blhs]} ft")
    if null_count == 0:
        print("[A3b] PASS — no null BLH remaining in H1-2024 window.")
    else:
        print(f"[A3b] WARNING — {null_count:,} null BLH values remain (ERA5 may not cover those timestamps).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("ERA5 BLH Backfill — Pittsburgh H1-2024")
    print("=" * 60)
    fetch_era5_blh()
    build_tidy_csv()
    patch_raw_csv()
    verify_patch()
    print("=" * 60)
    print("Done.  Next: re-run merge_smell_weather_pittsburgh.py")
    print("=" * 60)
