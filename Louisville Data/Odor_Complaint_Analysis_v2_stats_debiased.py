import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import os

os.makedirs("odor_plots", exist_ok=True)
plot_counter = 0

def custom_show():
    global plot_counter
    plot_counter += 1
    filename = f"odor_plots/odor_plot_{plot_counter}.png"
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    plt.close()

plt.show = custom_show

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import os

os.makedirs("Louisville Data/odor_plots", exist_ok=True)
plot_counter = 0

def custom_show():
    global plot_counter
    plot_counter += 1
    filename = f"Louisville Data/odor_plots/odor_plot_{plot_counter}_debiased.png"
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    plt.close()

plt.show = custom_show

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import pearsonr
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import warnings

warnings.filterwarnings('ignore')
sns.set_theme(style="whitegrid")


# ==========================================

# Load the merged dataset we generated
import os
file_path = 'open-meteo-smell-merged.csv'
if not os.path.exists(file_path) and os.path.exists(os.path.join('Louisville Data', file_path)):
    file_path = os.path.join('Louisville Data', file_path)
elif not os.path.exists(file_path) and os.path.exists(os.path.join('Data', file_path)):
    file_path = os.path.join('Data', file_path)

print(f"Reading dataset from: {file_path}")
df_raw = pd.read_csv(file_path)

# Map our columns to the names expected by the notebook
column_mapping = {
    'time': 'datetime',
    'smell_report_count': 'complaints',
    'temperature_2m (°F)': 'temperature',
    'relative_humidity_2m (%)': 'relative_humidity',
    'wind_speed_10m (mp/h)': 'wind_speed',
    'wind_direction_10m (°)': 'wind_direction',
    'rain (inch)': 'precipitation',
    'dew_point_2m (°F)': 'dew_point',
    'vapour_pressure_deficit (kPa)': 'vapor_pressure',
    'surface_pressure (hPa)': 'atmospheric_pressure',
    'shortwave_radiation (W/m²)': 'solar_radiation',
    'sunshine_duration (s)': 'sunshine_duration',
    'boundary_layer_height (ft)': 'boundary_layer_height'
}
df_mapped = df_raw.rename(columns=column_mapping)
df_mapped['datetime'] = pd.to_datetime(df_mapped['datetime'])

# Keep the zipcode-level hourly data in a separate variable
df_zipcode = df_mapped.copy()

# Aggregate the zipcode-level data to a city-wide hourly dataset for baseline analysis
df = df_mapped.groupby('datetime').agg({
    'complaints': 'sum',
    'temperature': 'mean',
    'precipitation': 'mean',
    'wind_speed': 'mean',
    'wind_direction': 'mean',
    'dew_point': 'mean',
    'relative_humidity': 'mean',
    'vapor_pressure': 'mean',
    'atmospheric_pressure': 'mean',
    'sunshine_duration': 'mean',
    'solar_radiation': 'mean',
    'boundary_layer_height': 'mean',
    'smell_value_average': 'mean'
}).reset_index()

# Ensure required temporal columns exist for hourly distributions
df['date'] = df['datetime'].dt.date
df['hour'] = df['datetime'].dt.hour
df['dayofweek'] = df['datetime'].dt.dayofweek
df['month'] = df['datetime'].dt.month
df['is_weekend'] = df['dayofweek'].isin([5, 6])

print("Hourly city-wide data loaded successfully! Shape:", df.shape)

# Aggregate hourly data to daily data for meteorological analysis
# As per the paper's methodology, correlation and regression analyses use daily metrics.
daily_df = df.groupby('date').agg({
    'complaints': 'sum',
    'is_weekend': 'first',
    'temperature': ['mean', 'min', 'max'],
    'precipitation': 'sum',
    'wind_speed': 'mean',
    'wind_direction': 'mean',
    'dew_point': 'mean',
    'relative_humidity': 'mean',
    'vapor_pressure': 'mean',
    'atmospheric_pressure': 'mean',
    'sunshine_duration': 'sum',
    'solar_radiation': 'mean',
    'boundary_layer_height': 'mean',
    'smell_value_average': 'mean'
}).reset_index()

# Flatten multi-index columns
daily_df.columns = [
    'date', 'complaints', 'is_weekend', 
    'temperature', 'temp_min', 'temp_max', 
    'precipitation', 'wind_speed', 'wind_direction', 
    'dew_point', 'relative_humidity', 'vapor_pressure', 
    'atmospheric_pressure', 'sunshine_duration', 
    'solar_radiation', 'boundary_layer_height', 'smell_value_average'
]

# Calculate Diurnal Temperature Range (DTR)
daily_df['diurnal_temperature_range'] = daily_df['temp_max'] - daily_df['temp_min']

# Create a temperature bin column for grouping
daily_df['temp_bin'] = pd.qcut(daily_df['temperature'], q=10, labels=False)

print("Daily city-wide aggregation complete! Shape:", daily_df.shape)


# ==========================================

fig, axes = plt.subplots(1, 2, figsize=(16, 5))

# Hourly Distribution (Fig. 2)
sns.boxplot(x='hour', y='complaints', data=df, color='lightblue', showfliers=False, ax=axes[0])
axes[0].set_title('Temporal Distribution by Time of Day (Fig. 2)')
axes[0].set_xlabel('Time of day')
axes[0].set_ylabel('Odor complaints')

# Weekly Distribution (Fig. 3)
sns.boxplot(x='dayofweek', y='complaints', data=df, color='lightgray', showfliers=False, ax=axes[1])
axes[1].set_xticks(range(7))
axes[1].set_xticklabels(['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'])
axes[1].set_title('Weekly Distribution by Day of the Week (Fig. 3)')
axes[1].set_xlabel('Day of the week')

plt.tight_layout()
plt.show()


# ==========================================

# Separate data by weekdays and weekends to assess lifestyle behavior shifts
df_weekday = daily_df[~daily_df['is_weekend']]
df_weekend = daily_df[daily_df['is_weekend']]

meteo_vars = ['temperature', 'precipitation', 'wind_speed', 'wind_direction', 
              'dew_point', 'relative_humidity', 'vapor_pressure', 
              'atmospheric_pressure', 'sunshine_duration', 'solar_radiation']

results = []
for var in meteo_vars:
    r_wd, p_wd = pearsonr(df_weekday['complaints'], df_weekday[var])
    r_we, p_we = pearsonr(df_weekend['complaints'], df_weekend[var])
    results.append({
        'Meteorological Variable': var.replace('_', ' ').title(),
        'Weekday r': r_wd, 'Weekday p-value': p_wd,
        'Weekend r': r_we, 'Weekend p-value': p_we
    })
    
corr_table = pd.DataFrame(results).round(3)
print(corr_table)


# ==========================================

# Evaluate the associations between daily odor complaint frequencies and the top four meteorological drivers
key_vars = ['temperature', 'atmospheric_pressure', 'sunshine_duration', 'solar_radiation']
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
axes = axes.flatten()

for i, var in enumerate(key_vars):
    ax = axes[i]
    sns.regplot(x=var, y='complaints', data=df_weekday, ax=ax, label='Weekday', color='darkred', scatter_kws={'alpha':0.3})
    sns.regplot(x=var, y='complaints', data=df_weekend, ax=ax, label='Weekend', color='darkblue', scatter_kws={'alpha':0.3})
    ax.set_title(f'Odor Complaints vs {var.replace("_", " ").title()}')
    ax.legend()

plt.tight_layout()
plt.show()


# ==========================================

def plot_pca_biplot(data, title):
    features = meteo_vars + ['complaints']
    
    # PCA requires standardization
    x = StandardScaler().fit_transform(data[features])
    pca = PCA(n_components=2)
    pcs = pca.fit_transform(x)
    
    # Calculate variable loadings to map features onto the 2D plane
    loadings = pca.components_.T * np.sqrt(pca.explained_variance_)

    plt.figure(figsize=(8, 8))
    
    # Plot variable vectors as arrows
    for i, feature in enumerate(features):
        color = 'red' if feature == 'complaints' else 'black'
        plt.arrow(0, 0, loadings[i, 0], loadings[i, 1], color=color, alpha=0.8, head_width=0.03)
        plt.text(loadings[i, 0]*1.15, loadings[i, 1]*1.15, feature.replace('_', ' ').title(), 
                 color=color, ha='center', va='center', fontsize=10)
        
    plt.xlim(-1.2, 1.2)
    plt.ylim(-1.2, 1.2)
    plt.axhline(0, color='gray', linestyle='--', alpha=0.5)
    plt.axvline(0, color='gray', linestyle='--', alpha=0.5)
    plt.xlabel(f'PC 1 ({pca.explained_variance_ratio_[0]*100:.1f}%)')
    plt.ylabel(f'PC 2 ({pca.explained_variance_ratio_[1]*100:.1f}%)')
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.show()

# Separate PCA for weekdays and weekends as done in the paper
plot_pca_biplot(df_weekday, 'PCA Biplot - Weekdays')
plot_pca_biplot(df_weekend, 'PCA Biplot - Weekends')


# ==========================================

zipcode_complaints = df_zipcode.groupby('zipcode')['complaints'].sum().sort_values(ascending=False).reset_index()
plt.figure(figsize=(12, 6))
sns.barplot(x='zipcode', y='complaints', data=zipcode_complaints, palette='viridis')
plt.title('Total Odor Complaints by Zipcode')
plt.xticks(rotation=45)
plt.xlabel('Zipcode')
plt.ylabel('Total Complaints')
plt.tight_layout()
plt.show()


# ==========================================

# Daily Correlations by Zipcode
valid_zips = zipcode_complaints[zipcode_complaints['complaints'] >= 10]['zipcode'].tolist()
print(f"Analyzing {len(valid_zips)} zipcodes with >= 10 complaints.")
meteo_vars = ['temperature', 'precipitation', 'wind_speed', 'wind_direction', 
              'dew_point', 'relative_humidity', 'vapor_pressure', 
              'atmospheric_pressure', 'sunshine_duration', 'solar_radiation', 'boundary_layer_height']

daily_results = []
for zip_code in valid_zips:
    df_zip_hourly = df_zipcode[df_zipcode['zipcode'] == zip_code].copy()
    df_zip_hourly['date'] = df_zip_hourly['datetime'].dt.date
    df_zip_daily = df_zip_hourly.groupby('date').agg({
        'complaints': 'sum',
        'temperature': 'mean',
        'precipitation': 'sum',
        'wind_speed': 'mean',
        'wind_direction': 'mean',
        'dew_point': 'mean',
        'relative_humidity': 'mean',
        'vapor_pressure': 'mean',
        'atmospheric_pressure': 'mean',
        'sunshine_duration': 'sum',
        'solar_radiation': 'mean',
        'boundary_layer_height': 'mean'
    }).reset_index()
    
    zip_corrs = {'zipcode': zip_code}
    for var in meteo_vars:
        if df_zip_daily[var].std() == 0 or df_zip_daily['complaints'].std() == 0:
            r = np.nan
        else:
            r, _ = pearsonr(df_zip_daily['complaints'], df_zip_daily[var])
        zip_corrs[var] = r
    daily_results.append(zip_corrs)

df_daily_corr = pd.DataFrame(daily_results).set_index('zipcode')

plt.figure(figsize=(14, 8))
sns.heatmap(df_daily_corr, annot=True, cmap='coolwarm', fmt=".2f", vmin=-0.4, vmax=0.4)
plt.title('Daily Pearson Correlation between Odor Complaints and Weather by Zipcode')
plt.xlabel('Meteorological Variables')
plt.ylabel('Zipcode')
plt.tight_layout()
plt.show()


# ==========================================

top_3_zips = valid_zips[:3]

def get_wind_sector(degree):
    if pd.isna(degree):
        return np.nan
    sectors = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    idx = int(((degree + 22.5) % 360) / 45)
    return sectors[idx]

df_zipcode['wind_sector'] = df_zipcode['wind_direction'].apply(get_wind_sector)

fig, axes = plt.subplots(len(top_3_zips), 1, figsize=(12, 4 * len(top_3_zips)), sharex=False)
if len(top_3_zips) == 1:
    axes = [axes]

for idx, zip_code in enumerate(top_3_zips):
    df_zip = df_zipcode[df_zipcode['zipcode'] == zip_code]
    sector_complaints = df_zip.groupby('wind_sector')['complaints'].mean().reindex(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
    
    ax = axes[idx]
    sns.barplot(x=sector_complaints.index, y=sector_complaints.values, ax=ax, palette='Blues_d')
    ax.set_title(f'Average Hourly Odor Complaints by Wind Direction in Zip {zip_code}')
    ax.set_ylabel('Mean complaints/hour')
    ax.set_xlabel('Wind Direction Sector')

plt.tight_layout()
plt.show()


# ==========================================

top_10_zips = valid_zips[:10]
df_top_10 = df_zipcode[df_zipcode['zipcode'].isin(top_10_zips)].copy()
df_top_10['hour'] = df_top_10['datetime'].dt.hour

pivot_df = df_top_10.pivot_table(index='zipcode', columns='hour', values='complaints', aggfunc='mean')

plt.figure(figsize=(14, 6))
sns.heatmap(pivot_df, cmap='YlOrRd', annot=False)
plt.title('Average Odor Complaints by Hour of Day and Zipcode')
plt.xlabel('Hour of Day (Local Time)')
plt.ylabel('Zipcode')
plt.tight_layout()
plt.show()


# ==========================================

df_cool = daily_df[daily_df['temperature'] <= 68].copy()
df_hot = daily_df[daily_df['temperature'] > 68].copy()

print(f"Cool Days (<= 68°F) N: {len(df_cool)}")
print(f"Hot Days (> 68°F) N: {len(df_hot)}")

results_cool = []
results_hot = []

for var in meteo_vars:
    if len(df_cool) >= 2 and df_cool[var].std() > 0 and df_cool['complaints'].std() > 0:
        r_c, p_c = pearsonr(df_cool['complaints'], df_cool[var])
    else:
        r_c, p_c = np.nan, np.nan
        
    if len(df_hot) >= 2 and df_hot[var].std() > 0 and df_hot['complaints'].std() > 0:
        r_h, p_h = pearsonr(df_hot['complaints'], df_hot[var])
    else:
        r_h, p_h = np.nan, np.nan
        
    results_cool.append({'Variable': var.replace('_', ' ').title(), 'Cool r': r_c, 'Cool p-val': p_c})
    results_hot.append({'Variable': var.replace('_', ' ').title(), 'Hot r': r_h, 'Hot p-val': p_h})

df_cool_corr = pd.DataFrame(results_cool)
df_hot_corr = pd.DataFrame(results_hot)

df_piecewise = df_cool_corr.merge(df_hot_corr, on='Variable')
print(df_piecewise.round(3))


# ==========================================

# Plot piecewise regressions for Temperature
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

sns.regplot(x='temperature', y='complaints', data=df_cool, ax=axes[0], color='darkblue', scatter_kws={'alpha': 0.3})
axes[0].set_title('Odor Complaints vs Temperature (<= 68°F)')
axes[0].set_xlabel('Temperature (°F)')
axes[0].set_ylabel('Daily Odor Complaints')

sns.regplot(x='temperature', y='complaints', data=df_hot, ax=axes[1], color='darkred', scatter_kws={'alpha': 0.3})
axes[1].set_title('Odor Complaints vs Temperature (> 68°F)')
axes[1].set_xlabel('Temperature (°F)')
axes[1].set_ylabel('Daily Odor Complaints')

plt.tight_layout()
plt.show()


# ==========================================

import statsmodels.api as sm

# Selected variables for modeling (including is_weekend to control for weekly reporting shifts)
model_vars = ['temperature', 'temperature_squared', 'solar_radiation', 'relative_humidity', 
              'wind_speed', 'precipitation', 'diurnal_temperature_range', 
              'boundary_layer_height', 'atmospheric_pressure', 'is_weekend']

daily_df['temperature_squared'] = daily_df['temperature'] ** 2
daily_df['is_weekend'] = daily_df['is_weekend'].astype(int)

# Clean data for count models
df_count = daily_df[['complaints'] + model_vars].dropna()
X_count = df_count[model_vars]
X_count = sm.add_constant(X_count)
y_count = df_count['complaints']

# 1. OLS Linear Regression
ols_model = sm.OLS(y_count, X_count)
ols_res = ols_model.fit()
print("=== OLS Linear Regression Results (Daily Complaints Count) ===")
print(ols_res.summary())

# 2. Poisson Regression
poisson_model = sm.GLM(y_count, X_count, family=sm.families.Poisson())
poisson_res = poisson_model.fit()
print("\n=== Poisson Regression Results (Daily Complaints Count) ===")
print(poisson_res.summary())


# ==========================================

# Filter active days
df_severity = daily_df[daily_df['complaints'] > 0][['smell_value_average'] + model_vars].dropna()

X_sev = df_severity[model_vars]
X_sev = sm.add_constant(X_sev)
y_sev = df_severity['smell_value_average']

# Fit OLS severity model
severity_model = sm.OLS(y_sev, X_sev)
severity_res = severity_model.fit()
print("=== OLS Regression Results (Daily average smell severity 1-5 scale) ===")
print(severity_res.summary())


# ==========================================

# Define binary event
daily_df['is_odor_event'] = (daily_df['complaints'] > 5).astype(int)

df_logit = daily_df[['is_odor_event'] + model_vars].dropna()
X_logit = df_logit[model_vars]
X_logit = sm.add_constant(X_logit)
y_logit = df_logit['is_odor_event']

logit_model = sm.Logit(y_logit, X_logit)
logit_res = logit_model.fit()
print("=== Logit Regression Results for Odor Risk Index ===")
print(logit_res.summary())

# Display Odds Ratios
odds_ratios = np.exp(logit_res.params)
df_odds = pd.DataFrame({
    'Odds Ratio (OR)': odds_ratios,
    'Lower CI (95%)': np.exp(logit_res.conf_int()[0]),
    'Upper CI (95%)': np.exp(logit_res.conf_int()[1]),
    'p-value': logit_res.pvalues
})
print("\n--- Odds Ratios ---")
print(df_odds.round(4))

# Calculate daily ORI:
# 1. Raw prediction (with weekend adjustment included)
daily_df['odor_risk_index_raw'] = logit_res.predict(X_logit) * 100

# 2. De-biased prediction (with is_weekend set to 0.0, assuming continuous 24/7 operations)
X_logit_debiased = X_logit.copy()
if 'is_weekend' in X_logit_debiased.columns:
    X_logit_debiased['is_weekend'] = 0.0
daily_df['odor_risk_index'] = logit_res.predict(X_logit_debiased) * 100


# ==========================================

# Generate a range of temperatures
temp_range = np.linspace(daily_df['temperature'].min(), daily_df['temperature'].max(), 200)

# Create a prediction dataframe holding other variables at their mean
pred_df = pd.DataFrame({
    'const': 1.0,
    'temperature': temp_range,
    'temperature_squared': temp_range ** 2,
    'solar_radiation': daily_df['solar_radiation'].mean(),
    'relative_humidity': daily_df['relative_humidity'].mean(),
    'wind_speed': daily_df['wind_speed'].mean(),
    'precipitation': daily_df['precipitation'].mean(),
    'diurnal_temperature_range': daily_df['diurnal_temperature_range'].mean(),
    'boundary_layer_height': daily_df['boundary_layer_height'].mean(),
    'atmospheric_pressure': daily_df['atmospheric_pressure'].mean(),
    'is_weekend': 0.0 # Holding weekend at 0 (weekday baseline) for the curve
})

# Predict probabilities
pred_probs = logit_res.predict(pred_df)

plt.figure(figsize=(10, 6))
plt.plot(temp_range, pred_probs, color='darkorange', linewidth=3, label='Predicted Probability (Weekday)')

# Add actual scatter points (binned by temperature deciles)
binned_events = daily_df.groupby('temp_bin').agg({
    'temperature': 'mean',
    'is_odor_event': 'mean'
})
plt.scatter(binned_events['temperature'], binned_events['is_odor_event'], color='darkblue', s=80, zorder=5, label='Actual Binned Frequency')

plt.title('Predicted Probability of an Odor Event (>5 complaints) vs Temperature')
plt.xlabel('Temperature (°F)')
plt.ylabel('Odor Event Probability')
plt.legend()
plt.grid(True, alpha=0.3)
plt.show()


# ==========================================

daily_df['date_dt'] = pd.to_datetime(daily_df['date'])
sample_df = daily_df[(daily_df['date_dt'] >= '2024-05-01') & (daily_df['date_dt'] <= '2024-07-31')].copy().sort_values('date')

fig, ax1 = plt.subplots(figsize=(15, 6))

color = 'tab:orange'
ax1.set_xlabel('Date')
ax1.set_ylabel('Odor Risk Index (ORI, 0-100)', color=color)
ax1.plot(sample_df['date_dt'], sample_df['odor_risk_index'], color=color, linewidth=2, label='Odor Risk Index')
ax1.tick_params(axis='y', labelcolor=color)
ax1.set_ylim(0, 100)

ax2 = ax1.twinx()
color = 'tab:blue'
ax2.set_ylabel('Actual Daily Smell Reports', color=color)
ax2.bar(sample_df['date_dt'], sample_df['complaints'], color=color, alpha=0.5, width=0.8, label='Actual complaints')
ax2.tick_params(axis='y', labelcolor=color)

plt.title('Odor Risk Index (ORI) vs. Actual Daily Smell Reports (May - July 2024)')
fig.tight_layout()
plt.show()


# ==========================================

# Calculate predictions for the Poisson count model
# 1. Raw prediction (with weekend adjustment included)
df_count['predicted_complaints_raw'] = poisson_res.predict(X_count)
# Use raw predictions for the calibration plot (which must compare against observed raw counts)
df_count['predicted_complaints'] = df_count['predicted_complaints_raw']

# 2. De-biased prediction (with is_weekend set to 0.0, assuming continuous 24/7 operations)
X_count_debiased = X_count.copy()
if 'is_weekend' in X_count_debiased.columns:
    X_count_debiased['is_weekend'] = 0.0
df_count['predicted_complaints_debiased'] = poisson_res.predict(X_count_debiased)

plt.figure(figsize=(10, 6))

# Plot raw observations with transparency to show density
plt.scatter(df_count['predicted_complaints'], df_count['complaints'], alpha=0.2, color='tab:blue', label='Raw Daily Observations')

# Create a binned calibration curve: group by predicted values using quantiles
df_count['pred_bin'] = pd.qcut(df_count['predicted_complaints'], q=15, duplicates='drop')
binned_data = df_count.groupby('pred_bin').agg({
    'predicted_complaints': 'mean',
    'complaints': 'mean'
}).reset_index()

# Plot the binned calibration line
plt.plot(binned_data['predicted_complaints'], binned_data['complaints'], color='tab:red', marker='o', linewidth=2.5, label='Binned Calibration (Mean)')

# Plot the y = x line representing perfect calibration
plt.plot([0, 25], [0, 25], color='black', linestyle='--', linewidth=1.5, label='Perfect Calibration (y = x)')

plt.xlim(0, df_count['predicted_complaints'].max() * 1.1)
plt.ylim(0, 25) # Cap at 25 for visualization focus, as some extreme days have >50 complaints

plt.title('Poisson Model Calibration: Actual vs. Predicted Daily Odor Complaints')
plt.xlabel('Predicted Daily Complaints (Poisson Model)')
plt.ylabel('Actual Daily Complaints')
plt.legend()
plt.grid(True, alpha=0.3)
plt.show()
