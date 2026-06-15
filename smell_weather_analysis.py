import sys
print(f"Python Path: {sys.executable}")
print(f"Searching in: {sys.path}")

import pandas as pd
import seaborn as sns
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import pearsonr

csv_path = "Louisville Data/open-meteo-smell-merged.csv"

def perform_smell_analysis(csv_path):
    """
    Analyzes the correlation between smell reports and weather variables.
    Expected columns: 'smell_report_count', 'temperature', 'pressure', 'wind_speed'
    """
    # Load the dataset
    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        # Rename columns from open-meteo merged format to legacy format
        rename_dict = {
            'temperature_2m (°F)': 'temperature',
            'surface_pressure (hPa)': 'pressure',
            'wind_speed_10m (mp/h)': 'wind_speed'
        }
        df = df.rename(columns=rename_dict)
    except FileNotFoundError:
        print(f"Error: File not found at {csv_path}")
        return

    # 1. Statistical Correlation Matrix
    # We focus on the relationship between report counts and weather variables
    correlation_matrix = df[['smell_report_count', 'temperature', 'pressure', 'wind_speed']].corr()
    
    print("Correlation Matrix:")
    print(correlation_matrix['smell_report_count'].sort_values(ascending=False))

    # 2. Visualization: Heatmap
    plt.figure(figsize=(10, 8))
    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', fmt=".2f")
    plt.title('Correlation Heatmap: Smell Reports vs Weather Variables')
    plt.savefig('legacy_correlation_heatmap.png')

    # 3. Scatter Plots with Regression Lines
    # This helps visualize if the relationship is linear
    variables = ['temperature', 'pressure', 'wind_speed']
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    for i, var in enumerate(variables):
        sns.regplot(ax=axes[i], x=var, y='smell_report_count', 
                    data=df.sample(n=min(len(df), 5000), random_state=42), 
                    scatter_kws={'alpha':0.3}, ci=None)
        
        # Calculate p-value for significance
        corr_val, p_val = pearsonr(df[var], df['smell_report_count'])
        axes[i].set_title(f'{var.capitalize()} vs Reports\n(r={corr_val:.2f}, p={p_val:.4f})')

    plt.tight_layout()
    plt.savefig('legacy_scatter_regression.png')

if __name__ == "__main__":
    # Run the analysis using the path defined at the top of the file
    perform_smell_analysis(csv_path)