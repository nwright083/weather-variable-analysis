"""
ad_config.py — Configuration for ORI-triggered ad deployment.

All tunable parameters for the Smell My City ad trigger framework.
Edit the values below to change behavior. No other files need modification
for routine config changes.
"""

# ── Model & Threshold ────────────────────────────────────────────────────────
# Which forecast model to evaluate when deciding whether to trigger ads.
# Options: "pittsburgh_proximity", "exact_pittsburgh",
#           "calvert_fitted" (if fitted model exists)
MODEL_MODE = "pittsburgh_proximity"

# Activate ads when the ORI (0–1 probability) >= this value.
# 0.2038 is the F1-optimal threshold for the Pittsburgh Proximity-Enhanced
# model (F1 = 0.7341, AUC = 0.9038).
ORI_THRESHOLD = 0.2038

# ── Timing ────────────────────────────────────────────────────────────────────
# Which forecast day to evaluate, relative to today.
#   0 = today's forecast (same-day ads)
#   1 = tomorrow's forecast (one-day lead time)
#   2+ = further out (accuracy degrades; recommend <= 3)
FORECAST_HORIZON_DAYS = 0

# How many days to keep ads active after a trigger.
#   1 = day-of only (ads run the trigger day, then stop)
#   2 = trigger day + next day
#   etc.
CAMPAIGN_DURATION_DAYS = 1

# Minimum gap (in days) between the end of one campaign and the start of the
# next for the same tract. Prevents rapid on/off cycling (ad fatigue).
#   0 = no cooldown (campaigns can restart immediately)
COOLDOWN_DAYS = 0

# ── Scope ─────────────────────────────────────────────────────────────────────
# Granularity for ad targeting. Matches the geofence units.
#   "tract" = Census Tract GEOIDs (32 tracts around Calvert City)
#   "zip"   = ZIP codes (legacy fallback)
GRANULARITY = "tract"

# Which tracts to consider for ad deployment.
#   None = all tracts in the forecast (currently 32)
#   List of GEOID strings to limit scope, e.g.:
#     ["21157950101", "21157950102", "21145030100"]
TARGET_TRACTS = None

# Maximum number of tracts that can have active ad campaigns simultaneously.
# Acts as a budget safeguard. None = no limit.
MAX_ACTIVE_TRACTS = None

# ── Ad Provider ───────────────────────────────────────────────────────────────
# Which ad provider adapter to use.
#   "mock"   = logging only (no real ads, safe for testing)
#   "eltoro" = El Toro GeoFraming integration (not yet implemented)
AD_PROVIDER = "mock"

# ── Paths ─────────────────────────────────────────────────────────────────────
# Where to find forecast data (relative to repo root, or absolute).
# Defaults work for the standard repo layout.
import os as _os
_REPO_ROOT = _os.path.dirname(_os.path.abspath(__file__))
FORECAST_JSON = _os.path.join(_REPO_ROOT, "docs", "data", "forecast.json")
META_JSON = _os.path.join(_REPO_ROOT, "docs", "data", "meta.json")
STATE_FILE = _os.path.join(_REPO_ROOT, "ad_state.json")
LOG_FILE = _os.path.join(_REPO_ROOT, "ad_decisions.log")
