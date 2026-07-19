"""
ad_config.py — Configuration for ORI-triggered ad deployment.

All tunable parameters for the Smell My City ad trigger framework.
Edit the values below to change behavior. No other files need modification
for routine config changes.
"""

# ── Model & Threshold ────────────────────────────────────────────────────────
# Which forecast model to evaluate when deciding whether to trigger ads.
#   "exact_pittsburgh"     — city-wide model, no spatial terms (DEFAULT)
#   "pittsburgh_proximity" — adds wind-direction + distance-decay proximity terms
MODEL_MODE = "exact_pittsburgh"

# Each model has its OWN correct alert threshold. Binding them here (rather than a
# single shared number) is a money-safety guardrail: switching MODEL_MODE switches
# to that model's correct threshold automatically, so ads never fire at the wrong
# rate. `metric_key` names the authoritative field in model_metrics.json that the
# threshold is copied from; tests/test_ad_config_thresholds.py asserts they match so
# the values can't silently drift.
#
#   exact_pittsburgh     -> thr_opt_daily = 0.3681  (daily city-wide; a spatially-flat
#                           model must use the daily threshold, NOT the zip-day thr_opt
#                           0.0697, which is an evaluation artifact)
#   pittsburgh_proximity -> thr_opt       = 0.2038  (per-tract; scores vary by tract)
MODEL_REGISTRY = {
    "exact_pittsburgh":     {"threshold": 0.3681, "metric_key": "thr_opt_daily"},
    "pittsburgh_proximity": {"threshold": 0.2038, "metric_key": "thr_opt"},
}

# Optional manual override of the alert threshold (0–1 probability). Leave as None to
# use the selected model's bound threshold from MODEL_REGISTRY. Set a number only to
# deliberately override for a run/config.
ORI_THRESHOLD = None


def resolve_threshold(model_mode: str | None = None, override: float | None = None) -> float:
    """Return the alert threshold (0–1) for a model.

    Precedence: explicit `override` > the model's bound threshold in MODEL_REGISTRY.

    Args:
        model_mode: Model key; defaults to MODEL_MODE.
        override:   If not None, returned as-is (deliberate override).

    Raises:
        ValueError: if the model is not in MODEL_REGISTRY.
    """
    if override is not None:
        return override
    mode = model_mode or MODEL_MODE
    if mode not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model_mode {mode!r}. Known models: {sorted(MODEL_REGISTRY)}"
        )
    return MODEL_REGISTRY[mode]["threshold"]

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
# A hard budget safeguard. Keep this a concrete number (not None) for real spend.
MAX_ACTIVE_TRACTS = 8

# ── Ad Provider ───────────────────────────────────────────────────────────────
# Which ad provider adapter to use.
#   "mock"   = logging only (no real ads, safe for testing) — DEFAULT
#   "eltoro" = El Toro order-line toggling (pre-provisioned; see ad_providers/eltoro.py)
AD_PROVIDER = "mock"

# ── El Toro ───────────────────────────────────────────────────────────────────
# MONEY KILL-SWITCH. Even with `--live`, the El Toro provider will not perform real
# actions unless this is True. Leave False until you have verified everything.
ELTORO_ENABLED = False

# Environment: "prod" or "dev". Selects El Toro base URL + token endpoint.
ELTORO_ENV = "prod"

# Optional base-URL override (their docs warn the host will change). None = use the
# default for ELTORO_ENV baked into ad_providers/eltoro_client.py.
ELTORO_BASE_URL = None

# Pre-provisioned mapping file: {org_id, campaign_id, order_lines:{tract_geoid: order_line_id}}.
# Produced at setup. Git-ignored. Tracts not in it are never touched.
# Credentials are read from env vars ELTORO_CLIENT_ID / ELTORO_CLIENT_SECRET (or .env),
# NOT stored here.
import os as _os0
ELTORO_MAPPING_FILE = _os0.path.join(
    _os0.path.dirname(_os0.path.abspath(__file__)), "eltoro_order_lines.json"
)

# ── Deploy-window guard (business hours) ──────────────────────────────────────
# El Toro deploys are processed on weekday business hours (Eastern). This guard warns
# (or blocks) if a real run happens outside that window.
#   BUSINESS_HOURS_ENFORCEMENT: "warn" (log a warning, proceed) or "hard" (force dry-run)
BUSINESS_HOURS_TZ = "America/New_York"
BUSINESS_HOURS_START = 9   # 09:00 local
BUSINESS_HOURS_END = 17    # 17:00 local
BUSINESS_DAYS = (0, 1, 2, 3, 4)  # Mon–Fri (Mon=0)
BUSINESS_HOURS_ENFORCEMENT = "warn"

# ── Paths ─────────────────────────────────────────────────────────────────────
# Where to find forecast data (relative to repo root, or absolute).
# Defaults work for the standard repo layout.
import os as _os
_REPO_ROOT = _os.path.dirname(_os.path.abspath(__file__))
FORECAST_JSON = _os.path.join(_REPO_ROOT, "docs", "data", "forecast.json")
META_JSON = _os.path.join(_REPO_ROOT, "docs", "data", "meta.json")
STATE_FILE = _os.path.join(_REPO_ROOT, "ad_state.json")
LOG_FILE = _os.path.join(_REPO_ROOT, "ad_decisions.log")
