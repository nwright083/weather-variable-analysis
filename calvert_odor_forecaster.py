import streamlit as st
import pandas as pd
import numpy as np
import requests
import sqlite3
import datetime
import hashlib
import math
import os
import json
import pydeck as pdk

import odor_forecast_core as core
from odor_forecast_core import (
    IND_LAT, IND_LON, LOCATIONS,
    COEFFS_PITTSBURGH, COEFFS_EST_CALVERT,
    get_risk_meta,
)

# Streamlit-cached wrappers around the pure core fetchers
fetch_forecasts = st.cache_data(ttl=1800)(core.fetch_forecasts)
fetch_historical_weather = st.cache_data(ttl=3600)(core.fetch_historical_weather)

# ==========================================
# 1. DATABASE & GEOGRAPHY SETUP
# ==========================================
DB_PATH = "calvert_tester_logs.db"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tester_config.json")

def get_last_tester_name():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get("last_tester_name", "")
        except:
            pass
    return ""

def save_last_tester_name(name):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump({"last_tester_name": name}, f)
    except:
        pass

ADMIN_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".admin_config.json")

def hash_password(password, salt=None):
    import hashlib
    import os
    if salt is None:
        salt = os.urandom(16)
    else:
        try:
            salt = bytes.fromhex(salt)
        except:
            salt = salt.encode('utf-8')
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return key.hex(), salt.hex()

def verify_admin_password(username, password):
    default_user = "admin"
    default_pwd = "calvert2026"
    
    if os.path.exists(ADMIN_CONFIG_PATH):
        try:
            with open(ADMIN_CONFIG_PATH, 'r') as f:
                config = json.load(f)
            stored_user = config.get("username", "admin")
            stored_hash = config.get("password_hash")
            stored_salt = config.get("password_salt")
            if stored_hash and stored_salt:
                h, _ = hash_password(password, stored_salt)
                return username == stored_user and h == stored_hash
        except:
            pass
            
    return username == default_user and password == default_pwd

def save_admin_credentials(username, password):
    try:
        h, s = hash_password(password)
        with open(ADMIN_CONFIG_PATH, 'w') as f:
            json.dump({
                "username": username,
                "password_hash": h,
                "password_salt": s
            }, f)
        return True
    except:
        return False

# IND_LAT, IND_LON, PRESSURE_ELEVATION_OFFSET, LOCATIONS are now in odor_forecast_core.

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if 'dispatches' table has the 'location' column to handle schema updates
    try:
        cursor.execute("SELECT location FROM dispatches LIMIT 1")
    except sqlite3.OperationalError:
        # Table exists but is missing 'location' column (or doesn't exist)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dispatches'")
        if cursor.fetchone():
            cursor.execute("DROP TABLE IF EXISTS reports")
            cursor.execute("DROP TABLE IF EXISTS dispatches")
            conn.commit()
            
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            location TEXT,
            predicted_ori REAL,
            wind_direction REAL,
            wind_speed REAL,
            pblh REAL,
            status TEXT DEFAULT 'Scheduled',
            UNIQUE(date, location)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatch_id INTEGER,
            tester_name TEXT,
            date_reported TEXT,
            odor_detected TEXT,
            severity INTEGER,
            comments TEXT,
            FOREIGN KEY (dispatch_id) REFERENCES dispatches(id)
        )
    """)
    conn.commit()
    
    # Schema migration: Add new columns if they do not exist
    for col_name, col_type in [("latitude", "REAL"), ("longitude", "REAL"), ("odor_description", "TEXT"), ("symptoms", "TEXT")]:
        try:
            cursor.execute(f"SELECT {col_name} FROM reports LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {col_name} {col_type}")
            conn.commit()
            
    conn.close()

init_db()

# calculate_bearing and check_wind_alignment are now in odor_forecast_core.

# ==========================================
# 2. OPEN-METEO MULTI-LOCATION FORECASTER
# ==========================================
# fetch_forecasts and fetch_historical_weather are imported from odor_forecast_core
# and wrapped with st.cache_data at the top of this file.


# ==========================================
# 3. PAGE INITIALIZATION & MINIMALIST STYLING
# ==========================================
st.set_page_config(
    page_title="Odor Risk Forecaster",
    page_icon="💨",
    layout="wide"
)

# Custom minimalist styling rules
st.markdown("""
<style>
    /* Minimalist layout overrides */
    .stApp {
        background-color: var(--background-color);
    }
    
    /* Style main area headers */
    [data-testid="stMain"] h1,
    [data-testid="stMain"] h2,
    [data-testid="stMain"] h3,
    [data-testid="stMain"] h4 {
        color: var(--text-color) !important;
        font-weight: 600 !important;
        letter-spacing: -0.015em;
    }

    /* Style sidebar headers specifically to adapt to the sidebar theme background */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4 {
        color: var(--text-color) !important;
        font-weight: 600 !important;
        letter-spacing: -0.015em;
    }
    
    /* Clean Cards */
    .clean-card {
        background-color: rgba(128, 128, 128, 0.08);
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: none;
    }
    
    /* Muted Minimal Badges */
    .badge-pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        font-size: 0.75rem;
        font-weight: 500;
        border-radius: 4px;
        text-align: center;
    }
    .badge-clear { background-color: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
    .badge-moderate { background-color: #fefdf0; color: #854d0e; border: 1px solid #fef08a; }
    .badge-elevated { background-color: #fff7ed; color: #9a3412; border: 1px solid #fed7aa; }
    .badge-high { background-color: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 500;
        color: var(--text-color);
        opacity: 0.6;
    }
    .stTabs [aria-selected="true"] {
        color: var(--text-color) !important;
        border-bottom-color: var(--text-color) !important;
        opacity: 1.0;
    }
</style>
""", unsafe_allow_html=True)

# Minimalist Title Section (No flashy banner gradients)
col_title, col_source = st.columns([3, 1])
with col_title:
    st.markdown("## Calvert City & Surrounding Counties Odor Risk Outlook")
    st.markdown("<p style='color:#64748b; margin-top:-10px; font-size:0.95rem;'>Odor trapping event forecasts for Marshall, McCracken, and Livingston Counties based on meteorological stagnation modeling.</p>", unsafe_allow_html=True)
with col_source:
    st.markdown("<div style='text-align:right; margin-top:5px;'><span class='badge-pill badge-clear' style='font-size:0.8rem; font-weight:600;'>🟢 Source: Open-Meteo (NWP + ERA5)</span></div>", unsafe_allow_html=True)

st.markdown("---")

# ==========================================
# 4. SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.markdown("### 🎛️ Parameters")

# COEFFS_PITTSBURGH and COEFFS_EST_CALVERT are now imported from odor_forecast_core.

mode = st.sidebar.selectbox(
    "Prediction Mode",
    options=["Estimated Calvert City", "Exact Pittsburgh Model", "Custom (Manual sliders)"],
    help=(
        "🔍 **Model Parameter Calibration Details**:\n\n"
        "• **Exact Pittsburgh Model**: Uses regression parameters trained directly on Pittsburgh's urban/hilly terrain dataset.\n\n"
        "• **Estimated Calvert City Model**: Calibrated specifically for rural river-basin geography:\n"
        "  - *Wind Speed Sensitivity*: Increased from -0.108 to -0.150 (calm winds pool odors faster in flat terrain).\n"
        "  - *Boundary Layer Sensitivity*: Increased from -0.00041 to -0.00060 (shallow nocturnal inversions trap odors more severely).\n"
        "  - *Baseline Intercept (Const)*: Raised from 17.42 to 18.00 to account for close-range chemical plant emissions."
    )
)

active_coeffs = {}
if mode == "Exact Pittsburgh Model":
    active_coeffs = COEFFS_PITTSBURGH.copy()
    st.sidebar.markdown("<small style='color:#64748b;'>Model parameters set exactly to the Pittsburgh baseline.</small>", unsafe_allow_html=True)
elif mode == "Estimated Calvert City":
    active_coeffs = COEFFS_EST_CALVERT.copy()
    st.sidebar.markdown("<small style='color:#64748b;'>Adjusted parameters for rural boundary layers and wind dispersion.</small>", unsafe_allow_html=True)
else:
    active_coeffs['const'] = st.sidebar.slider("Intercept (Const)", -30.0, 30.0, 18.0, 0.1)
    active_coeffs['temperature'] = st.sidebar.slider("Temperature", -0.5, 0.5, 0.114354, 0.001)
    active_coeffs['temperature_squared'] = st.sidebar.slider("Temp Squared", -0.005, 0.005, -0.000476, 0.00001)
    active_coeffs['solar_radiation'] = st.sidebar.slider("Solar Radiation", -0.1, 0.1, -0.013972, 0.001)
    active_coeffs['relative_humidity'] = st.sidebar.slider("Humidity", -0.2, 0.2, -0.057838, 0.001)
    active_coeffs['wind_speed'] = st.sidebar.slider("Wind Speed", -0.5, 0.5, -0.150000, 0.001)
    active_coeffs['precipitation'] = st.sidebar.slider("Precipitation", -2.0, 2.0, -0.864070, 0.01)
    active_coeffs['diurnal_temperature_range'] = st.sidebar.slider("Diurnal Range (DTR)", -0.5, 0.5, 0.229181, 0.001)
    active_coeffs['boundary_layer_height'] = st.sidebar.slider("Boundary Layer (BLH)", -0.005, 0.005, -0.000600, 0.00001)
    active_coeffs['atmospheric_pressure'] = st.sidebar.slider("Pressure", -0.1, 0.1, -0.017966, 0.001)

st.sidebar.markdown("---")
use_wind_filter = st.sidebar.toggle("Enable Wind Corridor Transport Filter", value=True)
wind_penalty_pct = st.sidebar.slider(
    "Odor Risk Penalty (Non-Corridor Winds) %",
    min_value=0, max_value=100, value=75, step=5,
    help="When wind blows away from a location, this scales the log-odds of an odor event. "
         "75% penalty → odds multiplied by 0.25 (log-odds −1.4). Applied before the sigmoid "
         "so ORI remains a calibrated probability."
)
wind_penalty = 1.0 - (wind_penalty_pct / 100.0)
wind_boost = st.sidebar.slider(
    "Odor Risk Boost (Corridor-Aligned Winds)",
    min_value=1.0, max_value=3.0, value=1.0, step=0.05,
    help="When wind aligns with the transport corridor, this multiplies the odds of an odor event. "
         "1.0 = neutral (no boost); 3.0 = odds tripled (log-odds +1.1). Applied in log-odds space "
         "before the sigmoid so ORI stays a calibrated probability."
)

# ==========================================
# 5. DATA INGESTION & CALCULATION
# ==========================================
forecast_df, is_mock = fetch_forecasts(LOCATIONS)

# predict_ori and get_risk_meta are now in odor_forecast_core (imported above).
forecast_df['ori'] = forecast_df.apply(
    lambda r: core.predict_ori(
        r, active_coeffs,
        use_wind_filter=use_wind_filter, wind_penalty=wind_penalty, wind_boost=wind_boost,
    ), axis=1)

# ==========================================
# 6. APP RENDER (MINIMALIST INTERFACE)
# ==========================================
tab_map, tab_details, tab_monthly, tab_log = st.tabs([
    "🗺️ Interactive Risk Map", 
    "📅 16-Day Forecast Outlook", 
    "📅 Monthly Calendar View", 
    "📋 Tester Dispatch Log"
])

# Get available dates
available_dates = sorted(forecast_df['date'].unique())

# --- TAB: MAP VIEW ---
with tab_map:
    col_map_sel, col_map_info = st.columns([1, 2])
    with col_map_sel:
        st.markdown("#### Forecast Date Selection")
        selected_date = st.selectbox("Select target date for map view:", options=available_dates, index=1)
        date_obj = datetime.datetime.strptime(selected_date, '%Y-%m-%d')
        st.markdown(f"**Target Date:** {date_obj.strftime('%A, %B %d, %Y')}")
        
    with col_map_info:
        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
        st.markdown(
            "This map displays the predicted **Odor Risk Index (ORI)** at each receiver location. "
            "The circle color represents the risk tier. The **dark gray circle** represents the Calvert City Industrial Complex (source location)."
        )

    # Filter data for selected date
    day_df = forecast_df[forecast_df['date'] == selected_date].copy()
    
    # Map color mapping for Pydeck
    day_df['color'] = day_df['ori'].apply(lambda ori: get_risk_meta(ori)[2])
    day_df['risk_tier'] = day_df['ori'].apply(lambda ori: get_risk_meta(ori)[0])
    
    # Load ZIP code boundaries and join metrics
    geojson_data = {}
    if os.path.exists("calvert_zips.geojson"):
        try:
            with open("calvert_zips.geojson", "r") as f:
                geojson_data = json.load(f)
        except Exception as e:
            st.sidebar.error(f"Error loading map polygons: {e}")
            
    zip_data_map = {}
    for _, row in day_df.iterrows():
        parts = row['location'].split(" ")
        if len(parts) > 1 and parts[1].isdigit():
            zip_code = parts[1]
            zip_data_map[zip_code] = {
                'ori': row['ori'],
                'color': row['color'],
                'risk_tier': row['risk_tier']
            }
            
    # Inject daily metrics into GeoJSON properties for Pydeck rendering
    if geojson_data and "features" in geojson_data:
        for feature in geojson_data['features']:
            z = feature['properties'].get('zip')
            if z in zip_data_map:
                feature['properties']['ori'] = zip_data_map[z]['ori']
                feature['properties']['risk_tier'] = zip_data_map[z]['risk_tier']
                # Add alpha (100) for translucency
                feature['properties']['fill_color'] = zip_data_map[z]['color'] + [100]
                
                # Fetch full ZIP location label
                match_row = day_df[day_df['location'].str.contains(z)]
                if not match_row.empty:
                    feature['properties']['location'] = match_row.iloc[0]['location']
                else:
                    feature['properties']['location'] = f"ZIP {z}"
            else:
                feature['properties']['ori'] = "N/A"
                feature['properties']['risk_tier'] = "N/A"
                feature['properties']['fill_color'] = [200, 200, 200, 50]
                feature['properties']['location'] = f"ZIP {z}"
                
    # Add industrial source to map df for visual reference
    source_record = {
        'location': 'Calvert City Industrial Complex (Emitters Center)',
        'latitude': IND_LAT,
        'longitude': IND_LON,
        'ori': 'N/A (Source)',
        'risk_tier': 'Source Location',
        'color': [100, 116, 139] # slate gray
    }
    source_df = pd.DataFrame([source_record])
    
    # Pydeck layer: Translucent ZIP code polygons
    if geojson_data:
        receiver_layer = pdk.Layer(
            "GeoJsonLayer",
            data=geojson_data,
            opacity=0.8,
            stroked=True,
            filled=True,
            extruded=False,
            wireframe=True,
            get_line_color=[71, 85, 105, 255], # Solid medium slate gray borders
            get_fill_color="properties.fill_color",
            line_width_min_pixels=1.5, # Thinner boundaries for a cleaner visual look
            pickable=True,
            auto_highlight=True
        )
    else:
        # Fallback to points if boundaries file is missing
        receiver_layer = pdk.Layer(
            "ScatterplotLayer",
            data=day_df,
            get_position=["longitude", "latitude"],
            get_color="color",
            get_radius=800,
            pickable=True,
            auto_highlight=True,
        )
    
    # Pydeck layer: Industrial Emitters Center
    source_layer = pdk.Layer(
        "ScatterplotLayer",
        data=source_df,
        get_position=["longitude", "latitude"],
        get_color="color",
        get_radius=1100,
        pickable=True,
    )
    
    # Pydeck Viewport zoomed out slightly to capture all ZIP boundaries
    view_state = pdk.ViewState(
        latitude=IND_LAT - 0.05,
        longitude=IND_LON,
        zoom=9.8,
        pitch=0
    )
    
    # Deck
    r_map = pdk.Deck(
        layers=[receiver_layer, source_layer],
        initial_view_state=view_state,
        tooltip={"text": "{location}\nOdor Risk Index: {ori}%\nRisk Tier: {risk_tier}"},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    )
    
    st.pydeck_chart(r_map)
    
    # Location Card list for selected day
    st.markdown("#### Location Breakdown for Selected Date")
    cols_loc = st.columns(len(day_df))
    for idx, (_, r) in enumerate(day_df.iterrows()):
        risk_t, badge_c, _ = get_risk_meta(r['ori'])
        with cols_loc[idx]:
            # Clean minimalist box
            st.markdown(f"""
            <div class="clean-card" style="text-align: center;">
                <div style="font-weight: 600; font-size: 0.85rem; height: 38px; overflow: hidden; color: var(--text-color); opacity: 0.9;">{r['location'].split('(')[0].strip()}</div>
                <div style="font-size: 1.6rem; font-weight: 700; color: var(--text-color); margin: 0.5rem 0;">{r['ori']}%</div>
                <span class="badge-pill {badge_c}">{risk_t}</span>
                <div style="font-size: 0.72rem; color: var(--text-color); opacity: 0.7; text-align: left; margin-top: 10px; border-top: 1px solid var(--border-color, #e2e8f0); padding-top: 8px; line-height:1.4;">
                    💨 Wind: {r['wind_speed']:.1f} mph @ {int(r['wind_direction'])}°<br>
                    🌁 PBLH: {int(r['boundary_layer_height'])} ft<br>
                    ☔ Rain: {r['precipitation']:.2f} in
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"Schedule Dispatch", key=f"btn_map_sched_{r['location']}_{r['date']}"):
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO dispatches (date, location, predicted_ori, wind_direction, wind_speed, pblh, status)
                        VALUES (?, ?, ?, ?, ?, ?, 'Scheduled')
                    """, (r['date'], r['location'], r['ori'], r['wind_direction'], r['wind_speed'], r['boundary_layer_height']))
                    conn.commit()
                    st.success(f"Scheduled dispatch for {r['location']} on {r['date']}!")
                except sqlite3.IntegrityError:
                    st.warning(f"Dispatch already exists for this date and location.")
                conn.close()
                st.rerun()

# --- TAB: 7-DAY CALENDAR VIEW ---
with tab_details:
    st.markdown("#### Location Outlets Outlook")
    selected_loc = st.selectbox("Select location to display forecast table:", options=list(LOCATIONS.keys()))
    
    loc_forecast = forecast_df[forecast_df['location'] == selected_loc].copy()
    
    num_cols = 8
    num_rows = math.ceil(len(loc_forecast) / num_cols)
    for r_idx in range(num_rows):
        row_df = loc_forecast.iloc[r_idx * num_cols : (r_idx + 1) * num_cols]
        cols_cal = st.columns(len(row_df))
        for c_idx, (_, r) in enumerate(row_df.iterrows()):
            item_idx = r_idx * num_cols + c_idx
            date_obj = datetime.datetime.strptime(r['date'], '%Y-%m-%d')
            day_n = date_obj.strftime('%a')
            date_lbl = date_obj.strftime('%b %d')
            
            risk_t, badge_c, color_rgb = get_risk_meta(r['ori'])
            color_h = f"rgb({color_rgb[0]}, {color_rgb[1]}, {color_rgb[2]})"
            
            # Highlight card border if High Risk
            card_border = f"border: 1.5px solid {color_h};" if risk_t == "High Risk" else "border: 1px solid var(--border-color, #e2e8f0);"
            
            with cols_cal[c_idx]:
                st.markdown(f"""
                <div class="clean-card" style="{card_border} text-align: center; padding: 0.8rem; margin-bottom: 0.5rem;">
                    <div style="font-weight: 600; color: var(--text-color); opacity: 0.9; font-size:0.85rem;">{day_n}</div>
                    <div style="font-size: 0.72rem; color: var(--text-color); opacity: 0.6;">{date_lbl}</div>
                    <div style="font-size: 1.7rem; font-weight: 700; margin: 0.4rem 0; color: {color_h};">{r['ori']}%</div>
                    <span class="badge-pill {badge_c}">{risk_t}</span>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"Dispatch", key=f"btn_cal_sched_{item_idx}"):
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO dispatches (date, location, predicted_ori, wind_direction, wind_speed, pblh, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'Scheduled')
                        """, (r['date'], selected_loc, r['ori'], r['wind_direction'], r['wind_speed'], r['boundary_layer_height']))
                        conn.commit()
                        st.success(f"Scheduled dispatch for {selected_loc} on {r['date']}!")
                    except sqlite3.IntegrityError:
                        st.warning("Dispatch already exists.")
                    conn.close()
                    st.rerun()

    # Minimalist Forecast Table
    st.markdown("#### Weather Parameters Data Table")
    tbl_df = loc_forecast.copy().rename(columns={
        'date': 'Date',
        'ori': 'Odor Risk (ORI %)',
        'temperature': 'Temp Mean (°F)',
        'wind_speed': 'Wind Speed (mph)',
        'wind_direction': 'Wind Dir (°)',
        'boundary_layer_height': 'PBL Height (ft)',
        'precipitation': 'Rain (in)',
        'diurnal_temperature_range': 'DTR (°F)',
        'relative_humidity': 'Humidity (%)'
    })
    st.dataframe(
        tbl_df[['Date', 'Odor Risk (ORI %)', 'Temp Mean (°F)', 'Wind Speed (mph)', 'Wind Dir (°)', 'PBL Height (ft)', 'Rain (in)', 'DTR (°F)', 'Humidity (%)']],
        width='stretch',
        hide_index=True
    )

# --- TAB: MONTHLY CALENDAR VIEW ---
with tab_monthly:
    st.markdown("#### 30-Day Historical Odor Risk Calendar")
    
    selected_loc_m = st.selectbox("Select location to display monthly calendar:", options=list(LOCATIONS.keys()), key="monthly_loc_sel")
    
    # Fetch historical data
    hist_df, is_hist_mock = fetch_historical_weather(LOCATIONS)
    
    # Calculate ORI for historical data using the same active coefficients
    hist_df['ori'] = hist_df.apply(
        lambda r: core.predict_ori(
            r, active_coeffs,
            use_wind_filter=use_wind_filter, wind_penalty=wind_penalty, wind_boost=wind_boost,
        ), axis=1)
    
    # Filter for the selected location
    loc_hist = hist_df[hist_df['location'] == selected_loc_m].copy()
    
    # Sort by date
    loc_hist = loc_hist.sort_values('date')
    
    if is_hist_mock:
        st.warning("⚠️ Open-Meteo Archive API offline. Displaying simulated historical baseline.")
    
    # Grid of past 30 days aligned by day of week
    loc_hist['datetime'] = pd.to_datetime(loc_hist['date'])
    loc_hist['weekday'] = loc_hist['datetime'].dt.weekday  # 0 = Monday, 6 = Sunday
    loc_hist['day_name'] = loc_hist['datetime'].dt.strftime('%a')
    loc_hist['day_num'] = loc_hist['datetime'].dt.day
    loc_hist['month_name'] = loc_hist['datetime'].dt.strftime('%b')
    
    # Display columns for Mon, Tue, Wed, Thu, Fri, Sat, Sun.
    col_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    cols_header = st.columns(7)
    for c_idx, day_name in enumerate(col_days):
        cols_header[c_idx].markdown(f"<div style='text-align: center; font-weight: 600; color: var(--text-color); opacity: 0.8; font-size: 0.9rem; padding-bottom: 5px; border-bottom: 2px solid var(--border-color, #e2e8f0);'>{day_name}</div>", unsafe_allow_html=True)
    
    # Prepend empty cells for padding
    first_date = loc_hist.iloc[0]
    first_weekday = first_date['weekday']
    grid_cells = [None] * first_weekday
    
    # Add all actual records
    for _, row in loc_hist.iterrows():
        grid_cells.append(row)
        
    # Append empty cells to complete the last week
    while len(grid_cells) % 7 != 0:
        grid_cells.append(None)
        
    # Render rows of the grid
    num_weeks = len(grid_cells) // 7
    for week_idx in range(num_weeks):
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        cols_week = st.columns(7)
        for d_idx in range(7):
            cell = grid_cells[week_idx * 7 + d_idx]
            with cols_week[d_idx]:
                if cell is None:
                    st.markdown("<div style='height: 145px; background-color: rgba(128, 128, 128, 0.03); border: 1px dashed rgba(128, 128, 128, 0.15); border-radius: 8px;'></div>", unsafe_allow_html=True)
                else:
                    risk_t, badge_c, color_rgb = get_risk_meta(cell['ori'])
                    color_h = f"rgb({color_rgb[0]}, {color_rgb[1]}, {color_rgb[2]})"
                    card_border = f"border: 1.5px solid {color_h};" if risk_t == "High Risk" else "border: 1px solid var(--border-color, #e2e8f0);"
                    
                    st.markdown(f"""
                    <div class="clean-card" style="{card_border} text-align: center; padding: 0.5rem; margin-bottom: 0.1rem; height: 110px; border-radius: 8px;">
                        <div style="font-size: 0.72rem; color: var(--text-color); opacity: 0.6; font-weight: 500;">{cell['month_name']} {cell['day_num']}</div>
                        <div style="font-size: 1.35rem; font-weight: 700; color: {color_h}; margin: 0.1rem 0;">{cell['ori']:.1f}%</div>
                        <span class="badge-pill {badge_c}" style="font-size: 0.65rem; padding: 0.05rem 0.25rem; display: inline-block;">{risk_t.split(' ')[0]}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Popover below the card to show detailed met data
                    with st.popover("🔍 Details", use_container_width=True):
                        st.markdown(f"##### Weather Details: {cell['date']}")
                        st.markdown(f"**Odor Risk Index (ORI):** `{cell['ori']}%` ({risk_t})")
                        st.markdown("---")
                        st.markdown(f"🌡️ **Temperature:** {cell['temperature']:.1f}°F (Min: {cell['temp_min']:.1f}°, Max: {cell['temp_max']:.1f}°)")
                        st.markdown(f"💨 **Wind:** {cell['wind_speed']:.1f} mph @ {int(cell['wind_direction'])}°")
                        st.markdown(f"🌁 **Boundary Layer:** {int(cell['boundary_layer_height'])} ft")
                        st.markdown(f"☔ **Rain:** {cell['precipitation']:.2f} in")
                        st.markdown(f"💧 **Humidity:** {cell['relative_humidity']:.1f}%")
                      # --- TAB: TESTER DISPATCH LOG ---
with tab_log:
    st.markdown("#### Paid Tester Management Panel")
    
    # Check query parameters for coordinates
    lat_val = 0.0
    lon_val = 0.0
    location_source = None
    
    if "lat" in st.query_params and "lon" in st.query_params:
        try:
            lat_val = float(st.query_params["lat"])
            lon_val = float(st.query_params["lon"])
            if st.query_params.get("skewed") == "true":
                location_source = "Skewed (Privacy Mode)"
            else:
                location_source = "Exact GPS"
        except:
            pass

    # Standard Smell My City choices
    ODOR_DESCRIPTIONS = [
        "Rotten eggs / Sulfur",
        "Sewage / Wastewater / Sewer",
        "Chemical / Solvent",
        "Industrial / Asphalt / Tar",
        "Animal / Slaughterhouse / Pigs",
        "Garbage / Trash / Landfill",
        "Gas / Natural Gas / Propane",
        "Smoke / Burning",
        "Petroleum / Fuel / Gasoline",
        "Musty / Moldy",
        "Other"
    ]
    
    SYMPTOMS = [
        "Headache",
        "Nausea",
        "Eye irritation / Burning eyes",
        "Sore throat / Throat irritation",
        "Coughing",
        "Shortness of breath / Hard to breathe",
        "Nose irritation / Burning nose",
        "Dizziness / Lightheadedness",
        "General disgust / Anxiety",
        "Other",
        "None"
    ]

    conn = sqlite3.connect(DB_PATH)
    dispatches_df = pd.read_sql_query("SELECT * FROM dispatches ORDER BY date DESC", conn)
    reports_df = pd.read_sql_query("""
        SELECT r.id, d.date, d.location, r.tester_name, r.date_reported, r.odor_detected, r.severity, r.comments, r.latitude, r.longitude, r.odor_description, r.symptoms 
        FROM reports r 
        LEFT JOIN dispatches d ON r.dispatch_id = d.id 
        ORDER BY r.date_reported DESC
    """, conn)
    conn.close()

    # Layout: Submission form and admin side
    col1, col2 = st.columns([1.1, 1.9])
    
    with col1:
        st.markdown("##### Record Tester Report")
        
        active_dispatches = dispatches_df[dispatches_df['status'] == 'Scheduled']
        
        report_type = st.radio(
            "Report Reference Type", 
            ["Scheduled Dispatch", "Ad-hoc / Unscheduled Report"], 
            horizontal=True,
            help="Select whether this feedback corresponds to a pre-scheduled dispatch or is an ad-hoc field observation."
        )
        
        selected_disp_str = None
        dispatch_id = None
        date_selected = None
        loc_selected = None
        
        if report_type == "Scheduled Dispatch":
            if active_dispatches.empty:
                st.info("No active tester dispatches scheduled. Use 'Ad-hoc' mode or schedule a dispatch from the Map or Calendar view.")
            else:
                dispatch_options = {
                    f"{r['date']} - {r['location'].split('(')[0].strip()} (ORI: {r['predicted_ori']:.1f}%)": r['id'] 
                    for _, r in active_dispatches.iterrows()
                }
                selected_disp_str = st.selectbox("Select Scheduled Dispatch Date", options=list(dispatch_options.keys()))
                if selected_disp_str:
                    dispatch_id = dispatch_options[selected_disp_str]
        else:
            date_selected = st.date_input("Date of Observation", value=datetime.date.today())
            loc_selected = st.selectbox("Observation Location", options=list(LOCATIONS.keys()))
        
        # Tester name autofill
        last_tester = get_last_tester_name()
        tester_name = st.text_input("Tester Name", value=last_tester, placeholder="e.g. Jane Smith")
        
        # Geolocation selection
        st.markdown("###### Geolocation")
        if location_source:
            st.success(f"📍 Location Loaded: **{location_source}**")
            
        col_coords = st.columns(2)
        with col_coords[0]:
            lat_input = st.number_input("Latitude", value=lat_val, format="%.6f", key="lat_input_field")
        with col_coords[1]:
            lon_input = st.number_input("Longitude", value=lon_val, format="%.6f", key="lon_input_field")
            
        col_geo_btns = st.columns(2)
        with col_geo_btns[0]:
            trigger_exact = st.button("📍 Get Exact Location", use_container_width=True)
        with col_geo_btns[1]:
            trigger_skewed = st.button("🛡️ Get Skewed Location (Privacy)", use_container_width=True)
            
        # Geolocation Javascript handling
        import streamlit.components.v1 as components
        if trigger_exact:
            components.html(
                """
                <script>
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(position) {
                            var lat = position.coords.latitude;
                            var lon = position.coords.longitude;
                            try {
                                var url = new URL(window.parent.location.href);
                                url.searchParams.set("lat", lat.toFixed(6));
                                url.searchParams.set("lon", lon.toFixed(6));
                                url.searchParams.delete("skewed");
                                window.parent.location.href = url.href;
                            } catch (e) {
                                try {
                                    var url = new URL(window.top.location.href);
                                    url.searchParams.set("lat", lat.toFixed(6));
                                    url.searchParams.set("lon", lon.toFixed(6));
                                    url.searchParams.delete("skewed");
                                    window.top.location.href = url.href;
                                } catch (e2) {
                                    alert("Browser sandbox blocked URL redirect. Coordinates obtained: Lat: " + lat.toFixed(6) + ", Lon: " + lon.toFixed(6));
                                }
                            }
                        },
                        function(error) {
                            alert("Error obtaining geolocation: " + error.message);
                        },
                        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                    );
                } else {
                    alert("Geolocation is not supported by this browser.");
                }
                </script>
                """,
                height=0,
                width=0,
            )
        elif trigger_skewed:
            components.html(
                """
                <script>
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(position) {
                            // Add noise of +/- 0.002 degrees (approx 200m)
                            var offsetLat = (Math.random() * 0.004) - 0.002;
                            var offsetLon = (Math.random() * 0.004) - 0.002;
                            var lat = position.coords.latitude + offsetLat;
                            var lon = position.coords.longitude + offsetLon;
                            try {
                                var url = new URL(window.parent.location.href);
                                url.searchParams.set("lat", lat.toFixed(6));
                                url.searchParams.set("lon", lon.toFixed(6));
                                url.searchParams.set("skewed", "true");
                                window.parent.location.href = url.href;
                            } catch (e) {
                                try {
                                    var url = new URL(window.top.location.href);
                                    url.searchParams.set("lat", lat.toFixed(6));
                                    url.searchParams.set("lon", lon.toFixed(6));
                                    url.searchParams.set("skewed", "true");
                                    window.top.location.href = url.href;
                                } catch (e2) {
                                    alert("Browser sandbox blocked URL redirect. Coordinates obtained: Lat: " + lat.toFixed(6) + ", Lon: " + lon.toFixed(6));
                                }
                            }
                        },
                        function(error) {
                            alert("Error obtaining geolocation: " + error.message);
                        },
                        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                    );
                } else {
                    alert("Geolocation is not supported by this browser.");
                }
                </script>
                """,
                height=0,
                width=0,
            )

        odor_detected = st.radio("Odor Detected?", ["Yes", "No"], index=1, horizontal=True)
        
        selected_descriptions = []
        selected_symptoms = []
        custom_symptom_desc = ""
        severity = 0
        
        if odor_detected == "Yes":
            severity = st.slider("Severity Value (1-5)", min_value=1, max_value=5, value=3, help="1 = Barely noticeable, 5 = Extreme/Overwhelming")
            selected_descriptions = st.multiselect("Odor Descriptions", options=ODOR_DESCRIPTIONS)
            selected_symptoms = st.multiselect("Symptoms experienced", options=SYMPTOMS)
            if "Other" in selected_symptoms:
                custom_symptom_desc = st.text_input("Specify Custom Symptoms", placeholder="e.g. skin irritation, nose watering")
            
        comments = st.text_area("Odor Observations / Additional Comments", placeholder="e.g., strong chemical smell, gasoline-like odor near Ledbetter")
        
        submit_btn = st.button("Submit Report", type="primary", use_container_width=True)
        
        if submit_btn:
            if report_type == "Scheduled Dispatch" and not selected_disp_str:
                st.error("No active scheduled dispatch selected.")
            elif not tester_name:
                st.error("Please enter the tester's name.")
            else:
                # Save tester name for autofill
                save_last_tester_name(tester_name)
                
                # Format multiselects and custom inputs
                odor_desc_str = "; ".join(selected_descriptions)
                
                symptoms_list = [s for s in selected_symptoms if s != "Other" and s != "None"]
                if "Other" in selected_symptoms and custom_symptom_desc:
                    symptoms_list.append(custom_symptom_desc)
                symptoms_str = "; ".join(symptoms_list) if symptoms_list else "None"
                
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if report_type == "Ad-hoc / Unscheduled Report":
                    date_str = date_selected.strftime('%Y-%m-%d')
                    cursor.execute("SELECT id FROM dispatches WHERE date = ? AND location = ?", (date_str, loc_selected))
                    row = cursor.fetchone()
                    if row:
                        dispatch_id = row[0]
                        cursor.execute("UPDATE dispatches SET status = 'Completed' WHERE id = ?", (dispatch_id,))
                    else:
                        cursor.execute("""
                            INSERT INTO dispatches (date, location, predicted_ori, wind_direction, wind_speed, pblh, status)
                            VALUES (?, ?, 0.0, 0.0, 0.0, 0.0, 'Completed')
                        """, (date_str, loc_selected))
                        dispatch_id = cursor.lastrowid
                
                cursor.execute("""
                    INSERT INTO reports (dispatch_id, tester_name, date_reported, odor_detected, severity, comments, latitude, longitude, odor_description, symptoms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (dispatch_id, tester_name, now_str, odor_detected, severity, comments, lat_input, lon_input, odor_desc_str, symptoms_str))
                
                if report_type == "Scheduled Dispatch":
                    cursor.execute("UPDATE dispatches SET status = 'Completed' WHERE id = ?", (dispatch_id,))
                    
                conn.commit()
                conn.close()
                
                # Clear geolocation query params so subsequent submissions are clean
                if "lat" in st.query_params:
                    del st.query_params["lat"]
                if "lon" in st.query_params:
                    del st.query_params["lon"]
                if "skewed" in st.query_params:
                    del st.query_params["skewed"]
                
                st.success("Successfully logged report!")
                st.rerun()
                
    with col2:
        # Initialize admin login state
        if "admin_logged_in" not in st.session_state:
            st.session_state.admin_logged_in = False
            
        if st.session_state.admin_logged_in:
            # Render Administrative Header
            col_admin_header = st.columns([3, 1])
            with col_admin_header[0]:
                st.markdown("##### 🔑 Administrator Dashboard (Authenticated)")
            with col_admin_header[1]:
                if st.button("Logout", key="btn_admin_logout", use_container_width=True):
                    st.session_state.admin_logged_in = False
                    st.rerun()
            
            st.markdown("---")
            
            # KPI Metrics Summary Row
            total_reports = len(reports_df)
            active_count = len(dispatches_df[dispatches_df['status'] == 'Scheduled'])
            
            if total_reports > 0:
                detected_count = len(reports_df[reports_df['odor_detected'] == 'Yes'])
                detection_rate = (detected_count / total_reports) * 100
                detected_reports = reports_df[reports_df['odor_detected'] == 'Yes']
                avg_severity = detected_reports['severity'].mean() if not detected_reports.empty else 0.0
            else:
                detection_rate = 0.0
                avg_severity = 0.0
                
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f"""
                <div class="clean-card" style="text-align: center; padding: 0.8rem; margin-bottom: 1rem;">
                    <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.7; font-weight: 500;">Active Dispatches</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: #3b82f6; margin: 0.1rem 0;">{active_count}</div>
                    <div style="font-size: 0.65rem; color: var(--text-color); opacity: 0.5;">Awaiting feedback</div>
                </div>
                """, unsafe_allow_html=True)
            with m2:
                st.markdown(f"""
                <div class="clean-card" style="text-align: center; padding: 0.8rem; margin-bottom: 1rem;">
                    <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.7; font-weight: 500;">Total Reports</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: #10b981; margin: 0.1rem 0;">{total_reports}</div>
                    <div style="font-size: 0.65rem; color: var(--text-color); opacity: 0.5;">Logged in system</div>
                </div>
                """, unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                <div class="clean-card" style="text-align: center; padding: 0.8rem; margin-bottom: 1rem;">
                    <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.7; font-weight: 500;">Odor Detection Rate</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: #f59e0b; margin: 0.1rem 0;">{detection_rate:.1f}%</div>
                    <div style="font-size: 0.65rem; color: var(--text-color); opacity: 0.5;">Of logged reports</div>
                </div>
                """, unsafe_allow_html=True)
            with m4:
                st.markdown(f"""
                <div class="clean-card" style="text-align: center; padding: 0.8rem; margin-bottom: 1rem;">
                    <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.7; font-weight: 500;">Average Severity</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: #ef4444; margin: 0.1rem 0;">{avg_severity:.2f} / 5</div>
                    <div style="font-size: 0.65rem; color: var(--text-color); opacity: 0.5;">For detected smells</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("##### Logged Tester Feedback Reports")
            if reports_df.empty:
                st.info("No reports logged yet.")
            else:
                # Create a headers row for the custom table
                cols_h = st.columns([1.2, 1.4, 0.9, 0.8, 0.8, 3.2, 0.7])
                cols_h[0].markdown("**Date**")
                cols_h[1].markdown("**Location**")
                cols_h[2].markdown("**Tester**")
                cols_h[3].markdown("**Odor?**")
                cols_h[4].markdown("**Severity**")
                cols_h[5].markdown("**Observations**")
                cols_h[6].markdown("**Action**")
                st.markdown("<hr style='margin: 0.2rem 0; opacity: 0.2;'>", unsafe_allow_html=True)
                
                # Loop through reports and display them as rows with inline action buttons
                for _, r in reports_df.iterrows():
                    cols_r = st.columns([1.2, 1.4, 0.9, 0.8, 0.8, 3.2, 0.7])
                    
                    cols_r[0].write(r['date'] if r['date'] else "N/A")
                    cols_r[1].write(r['location'].split('(')[0].strip() if r['location'] else "Ad-hoc")
                    cols_r[2].write(r['tester_name'])
                    cols_r[3].write(r['odor_detected'])
                    cols_r[4].write(str(r['severity']))
                    
                    # Group description, symptoms, coordinates, and comments into Observations
                    obs_parts = []
                    if r['odor_description']:
                        obs_parts.append(f"👃 **Smell:** {r['odor_description']}")
                    if r['symptoms']:
                        obs_parts.append(f"🤒 **Symptoms:** {r['symptoms']}")
                    if r['latitude'] is not None and r['longitude'] is not None and (r['latitude'] != 0.0 or r['longitude'] != 0.0):
                        obs_parts.append(f"📍 **Coords:** `{r['latitude']:.6f}, {r['longitude']:.6f}`")
                    if r['comments']:
                        obs_parts.append(f"💬 **Comments:** {r['comments']}")
                    obs_summary = "\n\n".join(obs_parts) if obs_parts else "No additional details"
                    
                    cols_r[5].markdown(obs_summary)
                    
                    # Inline delete button
                    if cols_r[6].button("🗑️", key=f"del_rep_btn_{r['id']}", help=f"Delete report {r['id']} by {r['tester_name']}"):
                        report_id_to_delete = r['id']
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        
                        cursor.execute("SELECT dispatch_id FROM reports WHERE id = ?", (report_id_to_delete,))
                        disp_id = cursor.fetchone()[0]
                        
                        cursor.execute("DELETE FROM reports WHERE id = ?", (report_id_to_delete,))
                        
                        cursor.execute("SELECT COUNT(*) FROM reports WHERE dispatch_id = ?", (disp_id,))
                        count = cursor.fetchone()[0]
                        
                        if count == 0:
                            cursor.execute("SELECT predicted_ori, status FROM dispatches WHERE id = ?", (disp_id,))
                            disp_row = cursor.fetchone()
                            if disp_row and disp_row[0] == 0.0 and disp_row[1] == 'Completed':
                                cursor.execute("DELETE FROM dispatches WHERE id = ?", (disp_id,))
                            else:
                                cursor.execute("UPDATE dispatches SET status = 'Scheduled' WHERE id = ?", (disp_id,))
                                
                        conn.commit()
                        conn.close()
                        st.success("Successfully deleted report!")
                        st.rerun()
                    st.markdown("<hr style='margin: 0.1rem 0; opacity: 0.1;'>", unsafe_allow_html=True)
                
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                
                # CSV downloads
                display_reports = reports_df.copy()
                display_reports.rename(columns={
                    'date': 'Odor Event Date',
                    'location': 'Location',
                    'tester_name': 'Tester Name',
                    'date_reported': 'Submission Time',
                    'odor_detected': 'Odor Detected?',
                    'severity': 'Reported Severity',
                    'comments': 'Observations',
                    'latitude': 'Latitude',
                    'longitude': 'Longitude',
                    'odor_description': 'Smell Description',
                    'symptoms': 'Symptoms'
                }, inplace=True)
                csv_cols = ['Odor Event Date', 'Location', 'Tester Name', 'Submission Time', 'Odor Detected?', 'Reported Severity', 'Latitude', 'Longitude', 'Smell Description', 'Symptoms', 'Observations']
                csv = display_reports[csv_cols].to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download CSV Feedback Log",
                    data=csv,
                    file_name="calvert_tester_reports.csv",
                    mime="text/csv",
                    use_container_width=True
                )
                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            st.markdown("##### Scheduled Dispatches Registry")
            if dispatches_df.empty:
                st.info("No dispatches scheduled yet.")
            else:
                st.dataframe(
                    dispatches_df[['date', 'location', 'predicted_ori', 'wind_direction', 'wind_speed', 'status']].rename(columns={
                        'date': 'Date',
                        'location': 'Location',
                        'predicted_ori': 'Forecasted ORI %',
                        'wind_direction': 'Wind Dir (°)',
                        'wind_speed': 'Wind Speed (mph)',
                        'status': 'Status'
                    }),
                    use_container_width=True,
                    hide_index=True
                )
                
                scheduled_only = dispatches_df[dispatches_df['status'] == 'Scheduled']
                if not scheduled_only.empty:
                    st.markdown("###### Cancel a Scheduled Dispatch")
                    cancel_options = {
                        f"{r['date']} - {r['location'].split('(')[0].strip()}": r['id']
                        for _, r in scheduled_only.iterrows()
                    }
                    c_col1, c_col2 = st.columns([3, 1])
                    with c_col1:
                        to_cancel_str = st.selectbox(
                            "Select dispatch to cancel", 
                            options=list(cancel_options.keys()), 
                            key="cancel_dispatch_select",
                            label_visibility="collapsed"
                        )
                    with c_col2:
                        if st.button("❌ Cancel", key="btn_cancel_dispatch", use_container_width=True):
                            dispatch_id_to_cancel = cancel_options[to_cancel_str]
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM dispatches WHERE id = ?", (dispatch_id_to_cancel,))
                            conn.commit()
                            conn.close()
                            st.success("Successfully cancelled dispatch!")
                            st.rerun()
                
                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
                
                with st.expander("⚙️ Change Admin Credentials", expanded=False):
                    st.write("Update the administrator username or password. Password updates will be securely hashed.")
                    current_admin_user = "admin"
                    if os.path.exists(ADMIN_CONFIG_PATH):
                        try:
                            with open(ADMIN_CONFIG_PATH, 'r') as f:
                                config = json.load(f)
                                current_admin_user = config.get("username", "admin")
                        except:
                            pass
                    
                    new_username = st.text_input("New Username", value=current_admin_user, key="change_username_field")
                    curr_password = st.text_input("Current Password", type="password", key="change_curr_password_field")
                    new_password = st.text_input("New Password", type="password", key="change_new_password_field")
                    confirm_password = st.text_input("Confirm New Password", type="password", key="change_confirm_password_field")
                    
                    if st.button("Update Credentials", key="btn_update_credentials", use_container_width=True):
                        if not curr_password or not new_password or not confirm_password:
                            st.error("All password fields are required.")
                        elif new_password != confirm_password:
                            st.error("New passwords do not match.")
                        else:
                            if verify_admin_password(current_admin_user, curr_password):
                                if save_admin_credentials(new_username, new_password):
                                    st.success("Credentials updated successfully!")
                                    st.rerun()
                                else:
                                    st.error("Failed to save updated credentials.")
                            else:
                                st.error("Incorrect current password.")

                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

                with st.expander("⚠️ Advanced Database Controls", expanded=False):
                    st.write("Danger Zone: Clearing the database will permanently delete all dispatches and tester feedback logs.")
                    if st.button("Clear All Database Logs", type="secondary", use_container_width=True):
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM reports")
                        cursor.execute("DELETE FROM dispatches")
                        conn.commit()
                        conn.close()
                        st.success("Cleared database logs successfully!")
                        st.rerun()
        else:
            # Login Form
            st.markdown("##### 🔒 Administrative Dashboard Sign-In")
            st.write("Viewing the feedback reports, metrics, registry, and downloads requires administrative credentials.")
            
            admin_user = st.text_input("Username", key="admin_username_input", placeholder="Enter username")
            admin_pwd = st.text_input("Password", type="password", key="admin_password_input", placeholder="Enter password")
            
            if st.button("Sign In", key="btn_admin_login", use_container_width=True, type="primary"):
                if verify_admin_password(admin_user, admin_pwd):
                    st.session_state.admin_logged_in = True
                    st.success("Access Granted!")
                    st.rerun()
                else:
                    st.error("Invalid Username or Password. Please try again.")

