"""
=============================================================================
 Local Air Odor Risk (LAOR) – Public Dashboard Mock-Up (4-Tier Examples)
 ─────────────────────────────────────────────────────────────────────────
 Self-contained script for Jupyter Notebook.
 Uses: matplotlib, seaborn, numpy  (no geopandas needed)
 Shows one representative day per LAOR tier with the city uniformly colored.
=============================================================================
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import PatchCollection
import matplotlib.patheffects as pe
import seaborn as sns
from matplotlib import rcParams
import json, os

# ──────────────────────────────────────────────────────────────────────────────
# 0.  CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", font_scale=1.05)
rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Helvetica Neue', 'Arial', 'DejaVu Sans']

TIER_COLORS = {
    'Clear / Low Risk':  '#2ecc71',
    'Moderate Risk':     '#f1c40f',
    'Elevated Risk':     '#e67e22',
    'High Risk':         '#e74c3c',
}
TIER_COLORS_LIGHT = {
    'Clear / Low Risk':  '#d5f5e3',
    'Moderate Risk':     '#fef9e7',
    'Elevated Risk':     '#fdebd0',
    'High Risk':         '#fadbd8',
}
TIER_TEXT = {
    'Clear / Low Risk':  'Fresh outdoor air. Ideal conditions for opening windows.',
    'Moderate Risk':     'Typical baseline air. Minor local odors possible in industrial pockets.',
    'Elevated Risk':     'Odor Notice: Stagnant weather conditions may trap local smells.',
    'High Risk':         'Odor Alert: High likelihood of noticeable ambient odor events today.',
}

DECILES      = [f'D{i}' for i in range(1, 11)]
TIER_MAP     = {
    'D1': 'Clear / Low Risk',  'D2': 'Clear / Low Risk',
    'D3': 'Moderate Risk',     'D4': 'Moderate Risk',     'D5': 'Moderate Risk',
    'D6': 'Elevated Risk',     'D7': 'Elevated Risk',     'D8': 'Elevated Risk',
    'D9': 'High Risk',         'D10': 'High Risk',
}
tier_names_ordered = ['Clear / Low Risk', 'Moderate Risk', 'Elevated Risk', 'High Risk']

# Synthetic calibration data (modeled after real Pittsburgh ORI output)
AVG_COMPLAINTS  = [9.2, 12.7, 16.2, 20.5, 23.4, 27.6, 37.8, 42.7, 65.5, 94.7]
EVENT_FREQ_PCT  = [0.3, 1.9, 5.2, 8.8, 14.9, 20.8, 35.7, 47.4, 67.2, 85.1]

# Mock example days for each tier
EXAMPLE_DAYS = {
    'Clear / Low Risk':  {'date': 'Jun 11, 2019', 'ori': 1,   'complaints': 18, 'temp': 61, 'wind': 7.7,  'blh': 'Normal', 'dtr': 'High'},
    'Moderate Risk':     {'date': 'Feb 07, 2018', 'ori': 9,   'complaints': 4,  'temp': 26, 'wind': 7.3,  'blh': 'Low',    'dtr': 'Normal'},
    'Elevated Risk':     {'date': 'Jun 03, 2020', 'ori': 31,  'complaints': 17, 'temp': 73, 'wind': 10.2, 'blh': 'Normal', 'dtr': 'High'},
    'High Risk':         {'date': 'Oct 12, 2022', 'ori': 75,  'complaints': 108, 'temp': 59, 'wind': 8.6,  'blh': 'Low',    'dtr': 'High'},
}

# ──────────────────────────────────────────────────────────────────────────────
# 1.  LOAD GEOJSON
# ──────────────────────────────────────────────────────────────────────────────
geo_path = os.path.join(os.path.dirname(os.path.abspath('__file__')),
                        'Pittsburgh Data', 'pittsburgh_zips.geojson')
if not os.path.exists(geo_path):
    for candidate in ['Pittsburgh Data/pittsburgh_zips.geojson',
                       '../Pittsburgh Data/pittsburgh_zips.geojson']:
        if os.path.exists(candidate):
            geo_path = candidate
            break

geojson = None
try:
    with open(geo_path, 'r') as f:
        geojson = json.load(f)
except Exception:
    pass

def parse_geo(geojson_data):
    patches, cx_list, cy_list, zl_list = [], [], [], []
    for feat in geojson_data['features']:
        geom = feat['geometry']
        coords_list = []
        if geom['type'] == 'Polygon':
            coords_list = [geom['coordinates'][0]]
        elif geom['type'] == 'MultiPolygon':
            coords_list = [poly[0] for poly in geom['coordinates']]
        for coords in coords_list:
            patches.append(plt.Polygon(coords, closed=True))
        all_x = [c[0] for r in coords_list for c in r]
        all_y = [c[1] for r in coords_list for c in r]
        cx_list.append(np.mean(all_x))
        cy_list.append(np.mean(all_y))
        zl_list.append(feat['properties'].get('ZCTA5CE20',
                       feat['properties'].get('ZCTA5CE10', '')))
    return patches, cx_list, cy_list, zl_list

# ──────────────────────────────────────────────────────────────────────────────
# 2.  FIGURE: Calibration (top) + 4 Tier Maps (bottom)
# ──────────────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(18, 14), facecolor='#f8f9fa')
gs = fig.add_gridspec(2, 4, height_ratios=[1, 1.1], hspace=0.30, wspace=0.22)

# ── 2a. Top: ORI Calibration Chart ──────────────────────────────────────────
ax_cal = fig.add_subplot(gs[0, :])

tier_ranges = [
    ('Clear / Low Risk',  -0.5, 1.5),
    ('Moderate Risk',      1.5, 4.5),
    ('Elevated Risk',      4.5, 7.5),
    ('High Risk',          7.5, 9.5),
]
for tn, xmin, xmax in tier_ranges:
    ax_cal.axvspan(xmin, xmax, color=TIER_COLORS_LIGHT[tn], alpha=0.55, zorder=0)

bar_colors = [TIER_COLORS[TIER_MAP[d]] for d in DECILES]
bars = ax_cal.bar(range(10), AVG_COMPLAINTS, color=bar_colors, alpha=0.85,
                  edgecolor='white', linewidth=1.2, zorder=2, width=0.7)
ax_cal.set_ylabel('Avg Daily Smell Reports', fontsize=12, fontweight='bold', color='#2c3e50')
ax_cal.set_xlabel('Odor Risk Index (ORI) Decile', fontsize=12, fontweight='bold', color='#2c3e50')
ax_cal.set_xticks(range(10))
ax_cal.set_xticklabels(DECILES, fontsize=10)
ax_cal.set_xlim(-0.6, 9.6)

for i, bar in enumerate(bars):
    h = bar.get_height()
    ax_cal.text(bar.get_x() + bar.get_width()/2., h + 0.3,
                f'{h:.1f}', ha='center', va='bottom', fontsize=8.5,
                fontweight='bold', color='#2c3e50', zorder=5)

ax_freq = ax_cal.twinx()
ax_freq.plot(range(10), EVENT_FREQ_PCT, color='#c0392b', marker='o', markersize=7,
             linewidth=2.5, zorder=4)
ax_freq.fill_between(range(10), EVENT_FREQ_PCT, alpha=0.07, color='#c0392b')
ax_freq.set_ylabel('Odor Event Frequency (%)', fontsize=12, fontweight='bold', color='#c0392b')
ax_freq.set_ylim(0, 105)
ax_freq.tick_params(axis='y', labelcolor='#c0392b')

for i, v in enumerate(EVENT_FREQ_PCT):
    ax_freq.text(i, v + 2, f'{v:.0f}%', ha='center', va='bottom', fontsize=8,
                 fontweight='bold', color='#c0392b', zorder=5)

for tn, xmin, xmax in tier_ranges:
    mid = (xmin + xmax) / 2.0
    ax_freq.annotate(tn, xy=(mid, 100), fontsize=9, fontweight='bold',
                     ha='center', va='bottom', color=TIER_COLORS[tn],
                     path_effects=[pe.withStroke(linewidth=2.5, foreground='white')])

ax_cal.set_title('ORI Calibration with LAOR Public Risk Tiers',
                 fontsize=14, fontweight='bold', color='#2c3e50', pad=15)
ax_cal.grid(axis='y', alpha=0.25, zorder=0)
ax_cal.set_axisbelow(True)

# ── 2b. Bottom: 4 Maps (one per tier) ──────────────────────────────────────
for col_idx, tier in enumerate(tier_names_ordered):
    ax_map = fig.add_subplot(gs[1, col_idx])
    day = EXAMPLE_DAYS[tier]

    if geojson is not None:
        _patches, _cx, _cy, _zl = parse_geo(geojson)
        _fc = [TIER_COLORS[tier]] * len(_patches)
        pc = PatchCollection(_patches, facecolors=_fc,
                             edgecolors='white', linewidths=0.4, alpha=0.85)
        ax_map.add_collection(pc)

        _mx = (max(_cx) - min(_cx)) * 0.06
        _my = (max(_cy) - min(_cy)) * 0.06
        ax_map.set_xlim(min(_cx) - _mx*3, max(_cx) + _mx*3)
        ax_map.set_ylim(min(_cy) - _my*3, max(_cy) + _my*3)

        for i in range(0, len(_zl), 5):
            ax_map.text(_cx[i], _cy[i], _zl[i], fontsize=4.5, ha='center', va='center',
                        color='#2c3e50', fontweight='bold', alpha=0.7,
                        path_effects=[pe.withStroke(linewidth=1.5, foreground='white')])



    ax_map.set_aspect('equal')
    ax_map.grid(alpha=0.1)
    ax_map.tick_params(labelsize=6)
    ax_map.set_title(tier, fontsize=11, fontweight='bold', color=TIER_COLORS[tier], pad=8)

    # Weather info overlay
    _box = f"{day['date']}\n"
    _box += f"ORI: {day['ori']}%  |  Reports: {day['complaints']}\n"
    _box += f"Temp: {day['temp']}°F  |  Wind: {day['wind']} mph\n"
    _box += f"BLH: {day['blh']}  |  DTR: {day['dtr']}"

    _text_color = 'white' if tier in ['High Risk', 'Elevated Risk'] else '#2c3e50'
    ax_map.text(0.50, 0.04, _box, transform=ax_map.transAxes,
                fontsize=7, verticalalignment='bottom', horizontalalignment='center',
                bbox=dict(boxstyle='round,pad=0.5', facecolor=TIER_COLORS[tier],
                          edgecolor='white', alpha=0.92),
                color=_text_color, fontfamily='monospace', fontweight='bold',
                linespacing=1.5)

# ── 3. Tier Table ──────────────────────────────────────────────────────────
fig.subplots_adjust(bottom=0.12)
ax_table = fig.add_axes([0.06, 0.01, 0.88, 0.08])
ax_table.axis('off')

tbl_data = [
    ['D1 – D2', 'Clear / Low Risk',  '< 5%',     TIER_TEXT['Clear / Low Risk']],
    ['D3 – D5', 'Moderate Risk',     '5% – 15%',  TIER_TEXT['Moderate Risk']],
    ['D6 – D8', 'Elevated Risk',     '15% – 55%', TIER_TEXT['Elevated Risk']],
    ['D9 – D10','High Risk',         '55% – 90%+',TIER_TEXT['High Risk']],
]
tbl = ax_table.table(cellText=tbl_data,
                     colLabels=['ORI Deciles', 'LAOR Tier', 'Event Freq.', 'Public Advisory'],
                     cellLoc='center', loc='center', colWidths=[0.10, 0.14, 0.10, 0.56])
tbl.auto_set_font_size(False)
tbl.set_fontsize(8.5)
for j in range(4):
    c = tbl[0, j]; c.set_facecolor('#2c3e50'); c.set_text_props(color='white', fontweight='bold')
    c.set_edgecolor('white'); c.set_height(0.18)
for i, rd in enumerate(tbl_data, start=1):
    tn = rd[1]
    for j in range(4):
        c = tbl[i, j]; c.set_facecolor(TIER_COLORS_LIGHT[tn]); c.set_edgecolor('white'); c.set_height(0.18)
        if j == 1: c.set_text_props(fontweight='bold', color=TIER_COLORS[tn])

fig.suptitle('Local Air Odor Risk (LAOR) – Public Communication Dashboard',
             fontsize=17, fontweight='bold', color='#2c3e50', y=0.98,
             fontstyle='italic')

# Save
output_path = os.path.join(os.path.dirname(os.path.abspath('__file__')),
                           'Pittsburgh Data', 'laor_public_dashboard.png')
fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f"✓ Dashboard saved → {output_path}")

plt.show()
