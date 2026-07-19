# El Toro Ad Integration — Setup & Operations

How the odor forecaster drives El Toro ads, how to turn it on safely, and the
questions still outstanding for El Toro.

Design rationale: [superpowers/specs/2026-07-19-eltoro-ad-integration-design.md](superpowers/specs/2026-07-19-eltoro-ad-integration-design.md)

---

## The two paths (why this is money-safe)

- **Setup (human, one-time, in the El Toro portal):** you + your rep create the
  campaign, geofenced targets, creatives, and **one order line per target tract**, each
  with a fixed budget/CPM. This is the *only* place spend amounts are ever set.
- **Daily (automated script):** only ever turns those pre-approved order lines **on or
  off**. It cannot create order lines, cannot change budgets, and refuses any tract not
  in the mapping file. Worst case: it toggles order lines whose spend you already capped.

## Files

| File | Purpose | Committed? |
|------|---------|-----------|
| `ad_trigger.py` | Daily decision engine (evaluate ORI → toggle order lines) | yes |
| `ad_config.py` | All tunables (model, thresholds, guardrails, El Toro settings) | yes |
| `ad_providers/eltoro_client.py` | Thin El Toro REST client (OAuth + endpoints) | yes |
| `ad_providers/eltoro.py` | Provider adapter: toggle pre-approved order lines | yes |
| `.env` | `ELTORO_CLIENT_ID` / `ELTORO_CLIENT_SECRET` | **no** (git-ignored) |
| `eltoro_order_lines.json` | `{org_id, campaign_id, order_lines:{tract:ol_id}}` | **no** (git-ignored) |
| `.env.example`, `eltoro_order_lines.example.json` | templates | yes |

## One-time setup

1. **Get credentials** from El Toro's team (they provision the client-credentials pair).
   `cp .env.example .env` and paste `ELTORO_CLIENT_ID` / `ELTORO_CLIENT_SECRET`.
2. **Provision in the portal** (with your rep): campaign + geofenced order lines with
   fixed budgets for the tracts you want to cover.
3. **Record the ids:** `cp eltoro_order_lines.example.json eltoro_order_lines.json` and
   fill `org_id`, `campaign_id`, and each `tract_geoid → order_line_id`.
4. **Confirm the toggle mechanism** with El Toro (see questions below), then set
   `_set_serving()` in `ad_providers/eltoro.py` if the default (requestReview /
   cancelDeployment) isn't right.
5. **Flip the switches** only when ready: `ad_config.ELTORO_ENABLED = True`, and run with
   `--live`.

## Running

```bash
# Safe dry run (default) — prints the plan, spends nothing:
python ad_trigger.py

# Choose the model (threshold follows automatically):
#   exact_pittsburgh -> 0.3681 (default),  pittsburgh_proximity -> 0.2038
python ad_trigger.py --model pittsburgh_proximity

# Go live (BOTH required for El Toro: --live AND ELTORO_ENABLED=True):
python ad_trigger.py --provider eltoro --live
```

Intended schedule: **each weekday morning (Eastern business hours)** after the forecast
refresh. The coverage window makes Friday's run cover Sat + Sun + Mon automatically.

## Guardrails (all on by default)

- **Dry-run by default.** Real spend needs `--live` **and** `ELTORO_ENABLED = True`.
- **Refuses unmapped tracts/order lines** — only touches ids in the mapping file.
- **`MAX_ACTIVE_TRACTS`** caps how many order lines can be simultaneously active.
- **Model-bound thresholds** so switching the model can't fire ads at the wrong rate.
- **Business-hours guard** (`warn` by default; set to `hard` to block off-hours deploys).
- **Never creates order lines or sets budgets** from the automated path.

## Model / threshold reference

| Model | Threshold | Source (`model_metrics.json`) |
|-------|-----------|-------------------------------|
| `exact_pittsburgh` (default) | 0.3681 | `exact_pittsburgh.thr_opt_daily` |
| `pittsburgh_proximity` | 0.2038 | `pittsburgh_proximity.thr_opt` |

---

## Questions still open for El Toro

### A. Order-line toggle lifecycle (fills `_set_serving()`)
1. After **`cancelDeployment`** on an order line that has already run, how do I turn it
   back on later — a fresh **`requestReview`** (re-review), or a **resume**?
2. Do **`pauseSchedules` / `playSchedules`** let me pause a live order line and resume it
   later **without re-review**? Is that the right toggle primitive?
3. Is there a **minimum flight duration**, or a limit on how often I can start/stop the
   same order line? (ad-fatigue / billing granularity)
4. Can I deploy a **1-day flight** (e.g., a high-odor Tuesday), or is the minimum a
   multi-day / weekend block?
5. Can a deployed (e.g., weekend) flight be **stopped early**, or is it committed once
   deployed?

### B. Deploy timing
6. Must the API **call itself** land during weekday business hours, or can I call any time
   and El Toro **queues** it for the next business-hours processing?
7. After a deploy is processed, **how long until ads actually serve** (instant / minutes /
   hours)? Can order-line toggling actually be done **24/7** via the API, or only in
   business hours?
8. Am I **billed only for serving time**, or also for paused/gap periods?

### C. Targeting & account
9. For census-tract **polygons**, what's the right El Toro product — a **geoframe** around
   the area, or an **IP-targeting audience** built from addresses in the tract? Does
   `create-json-target` accept polygons/GeoJSON?
10. What are my **`org_id`** and the **`campaign_id`** to use, and can order lines be
    listed/filtered by campaign via the API (`list-order-lines`) so I can auto-populate
    the mapping?
11. What is the correct **balance / billing** endpoint for a pre-flight spend check?

### D. Environment
12. Confirm the **production base URL** — docs say `https://hagrid.api.eltoro.com` but warn
    it "will change." What should I pin, and how will changes be communicated?
13. Any **rate limits** on the API I should respect from an automated daily job?
