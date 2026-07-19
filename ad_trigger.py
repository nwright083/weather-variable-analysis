"""
ad_trigger.py — ORI-triggered ad deployment decision engine for Smell My City.

Evaluates the current odor risk forecast for each census tract around Calvert City
and decides which tracts should have active Smell My City ad campaigns. Uses the
configured ad provider adapter to activate/deactivate campaigns.

Usage:
    python ad_trigger.py                  # run with defaults from ad_config.py
    python ad_trigger.py --dry-run        # evaluate without calling provider
    python ad_trigger.py --threshold 0.30 # override threshold for this run
    python ad_trigger.py --horizon 1      # evaluate tomorrow's forecast
    python ad_trigger.py --provider mock  # override provider for this run

Can be run locally, via cron, or as a GitHub Actions step. Does NOT modify the
forecast site — it only reads forecast.json and meta.json.
"""

import os
import sys
import json
import math
import argparse
import datetime
import logging

# ── Setup import path so ad_config / ad_providers resolve from repo root ──
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import ad_config
from ad_providers import get_provider

logger = logging.getLogger("ad_trigger")


# ──────────────────────────────────────────────────────────────────────────────
# Money-safety gates (pure, auditable)
# ──────────────────────────────────────────────────────────────────────────────

def effective_dry_run(
    *,
    live: bool,
    provider_name: str,
    eltoro_enabled: bool,
    force_dry_run: bool = False,
) -> bool:
    """Decide whether a run is dry (no provider calls) — the two-key live gate.

    A run performs real provider actions ONLY when the operator explicitly opts in
    with `live=True`, and — for the El Toro provider specifically — the
    ELTORO_ENABLED kill-switch is also on. Anything else is dry-run.

    Returns True for dry-run (safe), False to perform real actions.
    """
    if force_dry_run:
        return True
    if not live:
        return True
    if provider_name == "eltoro" and not eltoro_enabled:
        return True
    return False


def coverage_dates(run_date: datetime.date) -> list[datetime.date]:
    """Which forecast days a run should deploy for, given El Toro deploys during
    weekday business hours and campaigns then run on later days.

    - Mon–Thu run  -> cover the next day.
    - Friday run   -> cover Sat + Sun + Mon (no deploy happens over the weekend).
    - Sat/Sun run  -> cover the next day (not the intended cadence, but safe).
    """
    if run_date.weekday() == 4:  # Friday
        return [run_date + datetime.timedelta(days=n) for n in (1, 2, 3)]
    return [run_date + datetime.timedelta(days=1)]


def business_hours_status(
    dt_utc: datetime.datetime,
    *,
    tz_name: str,
    start_hour: int,
    end_hour: int,
    business_days,
) -> tuple[bool, datetime.datetime]:
    """Return (within_window, local_datetime) for a UTC datetime.

    Within = a business day AND start_hour <= local hour < end_hour.
    """
    local = dt_utc
    try:
        from zoneinfo import ZoneInfo
        local = dt_utc.astimezone(ZoneInfo(tz_name))
    except Exception:  # pragma: no cover - tz db missing; fall back to given time
        logger.warning(f"Could not load timezone {tz_name!r}; using UTC for business-hours check.")
    within = (local.weekday() in tuple(business_days)) and (start_hour <= local.hour < end_hour)
    return within, local


def _business_hours_guard(now_utc: datetime.datetime) -> bool:
    """Warn (or, in 'hard' mode, abort) if a real deploy runs outside El Toro's
    weekday business-hours window."""
    tz = getattr(ad_config, "BUSINESS_HOURS_TZ", "America/New_York")
    start = getattr(ad_config, "BUSINESS_HOURS_START", 9)
    end = getattr(ad_config, "BUSINESS_HOURS_END", 17)
    days = getattr(ad_config, "BUSINESS_DAYS", (0, 1, 2, 3, 4))
    mode = getattr(ad_config, "BUSINESS_HOURS_ENFORCEMENT", "warn")
    within, local = business_hours_status(
        now_utc, tz_name=tz, start_hour=start, end_hour=end, business_days=days
    )
    if not within:
        msg = (
            f"Deploy running outside El Toro business hours "
            f"({local:%a %Y-%m-%d %H:%M} {tz}). El Toro processes deploys on weekday "
            f"business hours; ads may not go live as expected."
        )
        if mode == "hard":
            raise RuntimeError(msg + "  [BUSINESS_HOURS_ENFORCEMENT='hard' — aborting run]")
        logger.warning(msg + "  [warn-only]")
    return within


# ──────────────────────────────────────────────────────────────────────────────
# ORI computation (mirrors model.js / odor_forecast_core.predict_ori)
# ──────────────────────────────────────────────────────────────────────────────

def compute_ori_from_features(cell: dict, coeffs: dict, pressure_offset: float) -> float:
    """Compute ORI (0–100%) from a feature dict and model coefficients.

    This mirrors the browser-side model.js computeOri() logic, using the
    default wind/distance settings from meta.json.

    Args:
        cell:     Feature dict from forecast.json (keys: temp, temp_sq, solar, rh, etc.)
        coeffs:   Model coefficients dict (keys: const, temperature, etc.)
        pressure_offset: Elevation pressure correction (typically 17.4 hPa).

    Returns:
        ORI as a float 0–100.
    """
    z = (
        coeffs["const"]
        + coeffs["temperature"] * cell["temp"]
        + coeffs["temperature_squared"] * cell["temp_sq"]
        + coeffs["solar_radiation"] * cell["solar"]
        + coeffs["relative_humidity"] * cell["rh"]
        + coeffs["wind_speed"] * cell["wind_speed"]
        + coeffs["precipitation"] * cell["precip"]
        + coeffs["diurnal_temperature_range"] * cell["dtr"]
        + coeffs["boundary_layer_height"] * cell["blh"]
        + coeffs["atmospheric_pressure"] * (cell["pressure"] - pressure_offset)
    )

    # Proximity regression terms (pittsburgh_proximity mode)
    if "multi_source_exposure" in coeffs and "distance" in cell:
        z += coeffs["multi_source_exposure"] * math.exp(-0.02 * cell["distance"])

    if "wind_align_weighted" in coeffs and "wind_alignment" in cell:
        z += coeffs["wind_align_weighted"] * cell["wind_alignment"]

    # Default wind filter: continuous alignment mode with penalty=0.75, boost=1.0
    if "wind_alignment" in cell:
        alignment = cell["wind_alignment"]
        penalty = 0.75  # matches meta.json wind_defaults.penalty_pct / 100
        boost = 1.0
        effective_mult = penalty + (boost - penalty) * alignment
        z += math.log(max(effective_mult, 1e-9))

    # Default distance decay: enabled with rate=0.02
    if "distance" in cell:
        z -= 0.02 * cell["distance"]

    z = max(-60.0, min(60.0, z))
    return round(100.0 / (1.0 + math.exp(-z)), 1)


# ──────────────────────────────────────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────────────────────────────────────

def load_state(path: str) -> dict:
    """Load ad campaign state from disk, or return empty state if file missing."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "last_run_utc": None,
        "active_campaigns": {},
        "history": [],
    }


def save_state(state: dict, path: str):
    """Persist ad campaign state to disk."""
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    logger.info(f"State saved to {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Decision engine
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_tracts(
    forecast_path: str,
    meta_path: str,
    model_mode: str,
    threshold: float,
    horizon_days: int,
) -> list[dict]:
    """Evaluate ORI for all tracts on the target forecast day.

    Returns a list of dicts:
        [{"tract_id": "21157950101", "name": "...", "ori": 42.3, "triggered": True}, ...]
    """
    with open(forecast_path) as f:
        forecast = json.load(f)
    with open(meta_path) as f:
        meta = json.load(f)

    coeffs = meta["coeffs"][model_mode]
    pressure_offset = meta.get("pressure_offset", 17.4)
    dates = forecast["dates"]
    locations = forecast["locations"]

    # Pick the target date
    if horizon_days >= len(dates):
        logger.warning(
            f"Horizon {horizon_days} exceeds available forecast days ({len(dates)}). "
            f"Using last available day: {dates[-1]}"
        )
        target_date = dates[-1]
    else:
        target_date = dates[horizon_days]

    logger.info(f"Evaluating {model_mode} model for date={target_date} (horizon={horizon_days}d)")

    features = forecast["features"].get(target_date, {})
    if not features:
        logger.error(f"No forecast features found for {target_date}")
        return []

    # Threshold is 0–1 probability, ORI is 0–100%; convert threshold to ORI scale
    threshold_ori = threshold * 100.0

    results = []
    for loc in locations:
        tract_id = loc["id"]
        tract_name = loc["name"]
        cell = features.get(tract_id)
        if cell is None:
            logger.warning(f"No features for tract {tract_id} ({tract_name}) on {target_date}")
            continue

        ori = compute_ori_from_features(cell, coeffs, pressure_offset)
        triggered = ori >= threshold_ori

        results.append({
            "tract_id": tract_id,
            "name": tract_name,
            "date": target_date,
            "ori": ori,
            "ori_probability": round(ori / 100.0, 4),
            "threshold": threshold,
            "threshold_ori": round(threshold_ori, 1),
            "triggered": triggered,
        })

    triggered_count = sum(1 for r in results if r["triggered"])
    logger.info(
        f"  {triggered_count}/{len(results)} tracts exceed threshold "
        f"({threshold:.1%} = ORI {threshold_ori:.1f})"
    )

    return results


def evaluate_window(
    forecast_path: str,
    meta_path: str,
    model_mode: str,
    threshold: float,
    target_dates: list[str],
) -> list[dict]:
    """Evaluate each tract's PEAK ORI across a set of forecast days.

    Used by the weekday-aware coverage window: a Friday deploy covers Sat/Sun/Mon, so a
    tract should get ads if ANY covered day is high-odor. We report the peak day and score.
    Target dates not present in the forecast are skipped (with a warning).

    Returns the same per-tract dict shape as evaluate_tracts, plus "covered_dates".
    """
    with open(forecast_path) as f:
        forecast = json.load(f)
    with open(meta_path) as f:
        meta = json.load(f)

    coeffs = meta["coeffs"][model_mode]
    pressure_offset = meta.get("pressure_offset", 17.4)
    locations = forecast["locations"]
    all_features = forecast["features"]

    present = [d for d in target_dates if d in all_features]
    missing = [d for d in target_dates if d not in all_features]
    if missing:
        logger.warning(
            f"Coverage day(s) {missing} not in forecast — skipping them. "
            f"Evaluating: {present or '(none)'}"
        )
    if not present:
        logger.error(f"No covered forecast days available (wanted {target_dates}).")
        return []

    threshold_ori = threshold * 100.0
    logger.info(
        f"Evaluating {model_mode} across {len(present)} covered day(s): {present} "
        f"(threshold {threshold:.1%} = ORI {threshold_ori:.1f})"
    )

    results = []
    for loc in locations:
        tract_id = loc["id"]
        tract_name = loc["name"]

        peak_ori = None
        peak_date = None
        for d in present:
            cell = all_features[d].get(tract_id)
            if cell is None:
                continue
            ori = compute_ori_from_features(cell, coeffs, pressure_offset)
            if peak_ori is None or ori > peak_ori:
                peak_ori = ori
                peak_date = d
        if peak_ori is None:
            logger.warning(f"No features for tract {tract_id} ({tract_name}) on any covered day")
            continue

        results.append({
            "tract_id": tract_id,
            "name": tract_name,
            "date": peak_date,
            "covered_dates": present,
            "ori": peak_ori,
            "ori_probability": round(peak_ori / 100.0, 4),
            "threshold": threshold,
            "threshold_ori": round(threshold_ori, 1),
            "triggered": peak_ori >= threshold_ori,
        })

    triggered_count = sum(1 for r in results if r["triggered"])
    logger.info(f"  {triggered_count}/{len(results)} tracts exceed threshold (peak across window)")
    return results


def apply_campaign_rules(
    results: list[dict],
    state: dict,
    duration_days: int,
    cooldown_days: int,
    max_active: int | None,
    target_tracts: list[str] | None,
) -> tuple[list[dict], list[dict]]:
    """Apply campaign duration, cooldown, and scope rules.

    Returns:
        (to_activate, to_deactivate): lists of action dicts
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    active = state.get("active_campaigns", {})

    to_activate = []
    to_deactivate = []

    # Filter to target tracts if specified
    if target_tracts:
        results = [r for r in results if r["tract_id"] in target_tracts]

    # Check for campaigns that should be deactivated (expired)
    for tract_id, campaign in list(active.items()):
        expires = datetime.datetime.fromisoformat(campaign["expires_utc"])
        if now_utc >= expires:
            # Check if still triggered — if so, extend; if not, deactivate
            matching = [r for r in results if r["tract_id"] == tract_id]
            if matching and matching[0]["triggered"]:
                # Still above threshold — extend campaign
                new_end = (now_utc + datetime.timedelta(days=duration_days)).strftime("%Y-%m-%d")
                campaign["expires_utc"] = (
                    now_utc + datetime.timedelta(days=duration_days)
                ).isoformat()
                logger.info(f"  Extending campaign for tract {tract_id} → expires {new_end}")
            else:
                to_deactivate.append({
                    "tract_id": tract_id,
                    "campaign_id": campaign["campaign_id"],
                    "reason": "expired",
                })

    # Check for new activations
    for r in results:
        tract_id = r["tract_id"]

        # Skip if already active
        if tract_id in active and tract_id not in [d["tract_id"] for d in to_deactivate]:
            continue

        if not r["triggered"]:
            continue

        # Check cooldown
        if cooldown_days > 0:
            history = state.get("history", [])
            last_deactivation = None
            for h in reversed(history):
                if h["tract_id"] == tract_id and h["action"] == "deactivate":
                    last_deactivation = datetime.datetime.fromisoformat(h["timestamp"])
                    break
            if last_deactivation:
                cooldown_end = last_deactivation + datetime.timedelta(days=cooldown_days)
                if now_utc < cooldown_end:
                    logger.info(
                        f"  Tract {tract_id} in cooldown until {cooldown_end.isoformat()} — skipping"
                    )
                    continue

        to_activate.append(r)

    # Apply max active limit
    if max_active is not None:
        current_active = len(active) - len(to_deactivate)
        slots_available = max(0, max_active - current_active)
        if len(to_activate) > slots_available:
            # Sort by ORI descending; activate highest-risk tracts first
            to_activate.sort(key=lambda r: r["ori"], reverse=True)
            dropped = to_activate[slots_available:]
            to_activate = to_activate[:slots_available]
            for d in dropped:
                logger.info(
                    f"  Tract {d['tract_id']} triggered (ORI={d['ori']:.1f}) but "
                    f"max_active={max_active} reached — skipping"
                )

    return to_activate, to_deactivate


def run_trigger(
    *,
    live: bool = False,
    dry_run: bool | None = None,
    threshold: float | None = None,
    horizon: int | None = None,
    provider_name: str | None = None,
    model_mode: str | None = None,
    provider=None,
    today: datetime.date | None = None,
):
    """Main entry point: evaluate forecast, apply rules, trigger ad provider.

    MONEY SAFETY: performs REAL provider actions only when `live=True` AND — for the
    El Toro provider — ad_config.ELTORO_ENABLED is True. Everything else is a dry run
    that computes and logs the plan but calls no provider. `dry_run=True` forces dry.

    Args:
        live:          Opt in to real actions (still gated by ELTORO_ENABLED for eltoro).
        dry_run:       Force a dry run regardless of `live` (used by --dry-run and tests).
        threshold:     Override the alert threshold (0–1). None → model's bound threshold.
        horizon:       Manual single-day override (indexes forecast dates). None → use the
                       weekday-aware coverage window.
        provider:      Inject an AdProvider (tests); None → build from provider_name.
        today:         Reference date for the coverage window (tests); None → today().
    """
    # Resolve config (args override > ad_config defaults)
    _model = model_mode or ad_config.MODEL_MODE
    _override = threshold if threshold is not None else ad_config.ORI_THRESHOLD
    _threshold = ad_config.resolve_threshold(_model, override=_override)
    _provider_name = provider_name or ad_config.AD_PROVIDER
    _duration = ad_config.CAMPAIGN_DURATION_DAYS
    _cooldown = ad_config.COOLDOWN_DAYS
    _max_active = ad_config.MAX_ACTIVE_TRACTS
    _target_tracts = ad_config.TARGET_TRACTS
    _eltoro_enabled = getattr(ad_config, "ELTORO_ENABLED", False)

    _dry = effective_dry_run(
        live=live,
        provider_name=_provider_name,
        eltoro_enabled=_eltoro_enabled,
        force_dry_run=bool(dry_run),
    )
    if live and not dry_run and _dry:
        logger.warning(
            f"--live requested but provider={_provider_name!r} is gated OFF "
            f"(ELTORO_ENABLED={_eltoro_enabled}). Running DRY — no spend."
        )

    # Load data
    if not os.path.exists(ad_config.FORECAST_JSON):
        logger.error(
            f"Forecast data not found at {ad_config.FORECAST_JSON}. "
            f"Run 'python generate_site.py' first."
        )
        return None

    # Which forecast day(s) does this run cover?
    if horizon is not None:
        with open(ad_config.FORECAST_JSON) as f:
            _fdates = json.load(f)["dates"]
        idx = min(horizon, len(_fdates) - 1)
        if horizon >= len(_fdates):
            logger.warning(
                f"Horizon {horizon} exceeds available forecast days ({len(_fdates)}); "
                f"using last day {_fdates[idx]}."
            )
        target_dates = [_fdates[idx]]
    else:
        _today = today or datetime.date.today()
        target_dates = [d.isoformat() for d in coverage_dates(_today)]

    results = evaluate_window(
        ad_config.FORECAST_JSON,
        ad_config.META_JSON,
        _model,
        _threshold,
        target_dates,
    )
    if not results:
        logger.error("No tracts evaluated — check forecast data.")
        return None

    state = load_state(ad_config.STATE_FILE)
    to_activate, to_deactivate = apply_campaign_rules(
        results, state, _duration, _cooldown, _max_active, _target_tracts
    )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    decisions = []

    if _dry:
        logger.info("=== DRY RUN — no provider calls will be made ===")
    else:
        if _provider_name == "eltoro":
            _business_hours_guard(now_utc)
        # Resolve the provider ONCE (injectable for tests).
        provider = provider or get_provider(_provider_name)

    # Deactivate expired campaigns
    for d in to_deactivate:
        decision = {
            "timestamp": now_utc.isoformat(),
            "tract_id": d["tract_id"],
            "action": "deactivate",
            "campaign_id": d["campaign_id"],
            "reason": d["reason"],
        }
        decisions.append(decision)

        if not _dry:
            provider.deactivate_campaign(d["campaign_id"])
            # Remove from active
            state["active_campaigns"].pop(d["tract_id"], None)

        logger.info(f"  DEACTIVATE tract={d['tract_id']} campaign={d['campaign_id']}")

    # Activate new campaigns
    for r in to_activate:
        start_date = r["date"]
        end_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d") + datetime.timedelta(
            days=_duration - 1
        )
        end_date = end_dt.strftime("%Y-%m-%d")
        expires_utc = (now_utc + datetime.timedelta(days=_duration)).isoformat()

        decision = {
            "timestamp": now_utc.isoformat(),
            "tract_id": r["tract_id"],
            "name": r["name"],
            "action": "activate",
            "ori": r["ori"],
            "ori_probability": r["ori_probability"],
            "start_date": start_date,
            "end_date": end_date,
        }
        decisions.append(decision)

        if not _dry:
            result = provider.activate_campaign(
                tract_id=r["tract_id"],
                tract_name=r["name"],
                start_date=start_date,
                end_date=end_date,
                ori_score=r["ori"] / 100.0,
                metadata={
                    "model_mode": _model,
                    "threshold": _threshold,
                    "covered_dates": r.get("covered_dates", [start_date]),
                },
            )
            campaign_id = result.get("campaign_id", "unknown")

            state["active_campaigns"][r["tract_id"]] = {
                "campaign_id": campaign_id,
                "activated_utc": now_utc.isoformat(),
                "expires_utc": expires_utc,
                "ori_at_activation": r["ori"],
                "provider": _provider_name,
            }

        logger.info(
            f"  ACTIVATE  tract={r['tract_id']} ({r['name']})  "
            f"ORI={r['ori']:.1f}  dates={start_date}→{end_date}"
        )

    # Update state
    state["last_run_utc"] = now_utc.isoformat()
    state["history"].extend(decisions)

    # Keep history manageable (last 500 entries)
    if len(state["history"]) > 500:
        state["history"] = state["history"][-500:]

    if not _dry:
        save_state(state, ad_config.STATE_FILE)

    # Write decision log
    _write_log(decisions, results, _model, _threshold, _dry)

    # Print summary
    print(f"\n{'═' * 60}")
    print(f"  Ad Trigger Summary  {'(DRY RUN)' if _dry else '(LIVE)'}")
    print(f"{'═' * 60}")
    print(f"  Model:     {_model}")
    print(f"  Threshold: {_threshold:.1%} (ORI ≥ {_threshold * 100:.1f})")
    print(f"  Covers:    {', '.join(target_dates)}")
    print(f"  Provider:  {_provider_name}")
    print(f"  Duration:  {_duration} day(s)")
    print(f"{'─' * 60}")
    print(f"  Tracts evaluated:  {len(results)}")
    print(f"  Above threshold:   {sum(1 for r in results if r['triggered'])}")
    print(f"  Campaigns activated: {len(to_activate)}")
    print(f"  Campaigns deactivated: {len(to_deactivate)}")
    print(f"{'═' * 60}\n")

    return {
        "results": results,
        "activated": to_activate,
        "deactivated": to_deactivate,
        "decisions": decisions,
    }


def _write_log(decisions, results, model_mode, threshold, dry_run):
    """Append today's decisions to the ad decisions log file."""
    now = datetime.datetime.now(datetime.timezone.utc)
    log_path = ad_config.LOG_FILE

    lines = [
        f"\n{'=' * 70}",
        f"Ad Trigger Run — {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        f"{'  [DRY RUN]' if dry_run else ''}",
        f"Model: {model_mode}  |  Threshold: {threshold:.1%}",
        f"{'-' * 70}",
    ]

    # All tract ORI scores
    lines.append("Tract ORI scores:")
    for r in sorted(results, key=lambda x: x["ori"], reverse=True):
        flag = "  ◄ ADS ON" if r["triggered"] else ""
        lines.append(f"  {r['tract_id']}  {r['name']:<45s}  ORI={r['ori']:5.1f}%{flag}")

    # Decisions
    if decisions:
        lines.append(f"\nDecisions:")
        for d in decisions:
            if d["action"] == "activate":
                lines.append(
                    f"  ✓ ACTIVATE  {d['tract_id']} ({d.get('name', '?')})  "
                    f"ORI={d['ori']:.1f}%  {d['start_date']}→{d['end_date']}"
                )
            elif d["action"] == "deactivate":
                lines.append(
                    f"  ✗ DEACTIVATE  {d['tract_id']}  campaign={d['campaign_id']}")
    else:
        lines.append("\nNo changes — all campaigns up to date.")

    lines.append(f"{'=' * 70}\n")

    log_text = "\n".join(lines)
    print(log_text)

    with open(log_path, "a") as f:
        f.write(log_text)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate odor forecast and trigger ad campaigns for Smell My City."
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Perform REAL provider actions. Default is dry-run (no spend). For the El Toro "
             "provider this ALSO requires ad_config.ELTORO_ENABLED = True."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Force a dry run (default behavior; explicit for clarity/scripts)."
    )
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Override ORI threshold (0–1). Default: the selected model's bound threshold."
    )
    parser.add_argument(
        "--horizon", type=int, default=None,
        help="Manual single-day override (indexes forecast dates). Default: weekday-aware "
             "coverage window (Fri covers the weekend)."
    )
    parser.add_argument(
        "--provider", type=str, default=None,
        help=f"Override ad provider. Default: {ad_config.AD_PROVIDER}"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Override model mode. Default: {ad_config.MODEL_MODE}"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging."
    )
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    run_trigger(
        live=args.live,
        dry_run=args.dry_run,
        threshold=args.threshold,
        horizon=args.horizon,
        provider_name=args.provider,
        model_mode=args.model,
    )


if __name__ == "__main__":
    main()
