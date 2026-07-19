# El Toro Ad Integration — Design Spec

**Date:** 2026-07-19
**Status:** Approved (pending spec review)
**Author:** Nicholas Wright + Claude

## Purpose

Finalize the odor-forecast-triggered ad system so that, once real El Toro API
credentials are available, the operator can paste in two values and run it. The
system evaluates the daily Odor Risk Index (ORI) forecast per census tract around
Calvert City and turns pre-approved El Toro **order lines** on or off accordingly.

The overriding requirement is **money safety**: real ad spend is significant, and
the automated daily path must not be able to create, resize, or run away with spend.

## Core safety principle: two separated paths

| Path | Who runs it | Frequency | Can it change money? |
|------|-------------|-----------|----------------------|
| **Setup** | Human, in the El Toro portal, with the rep | Once (and on changes) | Yes — sets budgets/CPM/targets/creatives |
| **Daily** | Automated script (cron / GitHub Actions) | Daily | **No** — only flips pre-approved order lines on/off |

The daily automated path:
- cannot create order lines,
- cannot set or change budgets,
- cannot touch any order line not explicitly listed in the mapping file,
- defaults to dry-run and requires two independent switches to spend.

Worst-case failure of the daily robot: it toggles order lines whose spend was
already capped by the human during setup.

## El Toro platform facts (from https://docs.api.eltoro.com/)

- **Auth:** OAuth2 **client-credentials** flow against Keycloak.
  - Token endpoint (prod): `https://auth.api.eltoro.com/auth/realms/eltoro/protocol/openid-connect/token`
  - Token endpoint (dev): `https://auth.api.dev.eltoro.com/auth/realms/eltoro/protocol/openid-connect/token`
  - Request: `POST`, `application/x-www-form-urlencoded`, params `grant_type=client_credentials`, `client_id`, `client_secret`.
  - Response: `{ "access_token": "...", "token_type": "bearer", "expires_in": 300 }` — **tokens expire in 5 minutes**, so the client must auto-refresh.
- **Base API URL (prod):** `https://hagrid.api.eltoro.com` (dev: `https://hagrid.api.dev.eltoro.com`).
  - Docs explicitly warn this hostname will change — keep it a single config constant.
- **Object model:** Org → Campaign → Order Lines. An **order line** is the unit that
  spends money (it carries a target/geofence, creative, CPM, budget, and flight dates).
- **Lifecycle:** Draft → `POST /v1/order-lines/:id:requestReview` → Review → Active/Serving.
  Stop with `POST /v1/order-lines/:id:cancelDeployment`.
- Relevant endpoints we use: `GET /v1/order-lines/:id` (get), `GET /v1/order-lines` (list),
  `:requestReview`, `:cancelDeployment`, `GET` balance (`get-balance`), and possibly
  `pauseSchedules` / `playSchedules` (see Open Question).

### Open question (confirm with El Toro rep — one-method fill-in)

How is an order line **re-enabled after being stopped**? Three possibilities, isolated
in a single private method `_set_serving()`:

1. **Re-review each time** — `cancelDeployment` then later `requestReview` again; not instant.
2. **Pause / Play (no re-review)** — `pauseSchedules` / `playSchedules`; instant, ideal.
3. **One-directional** — cancel tears down; re-enable requires clone/recreate; worst case.

Preferred answer: #2. The daily toggle strategy adapts to whichever is true without
changing anything outside `_set_serving()`. If #1, the script holds an order line on
for a minimum stretch rather than cycling daily.

Questions for the rep:
1. After `cancelDeployment` on an order line that has run, how do I turn it back on —
   re-review, or resume?
2. Do `pauseSchedules` / `playSchedules` pause a live order line and resume it without re-review?
3. Minimum flight duration / limit on start-stop frequency for the same order line?
4. On resume/re-deploy, how long until ads actually serve?
5. Am I billed for the paused gap, or only for serving time?

## Model selection and thresholds

Two forecast models exist in `docs/data/meta.json` (`coeffs` keys), each with its own
**correct** alert threshold. The threshold is bound to the model so switching the model
switches the threshold automatically.

| Model | Threshold | Source (meta.json → model_metrics) |
|-------|-----------|-------------------------------------|
| `exact_pittsburgh` (**default**) | **0.3681** | `exact_pittsburgh.thr_opt_daily` — the daily city-wide threshold; the model has no spatial terms |
| `pittsburgh_proximity` | **0.2038** | `pittsburgh_proximity.thr_opt` — per-tract (zip-day) threshold |

**Why this matters (money bug avoided):** the current `ad_config.py` hardcodes a single
threshold (0.2038) regardless of model. Flipping to `exact_pittsburgh` without changing it
would fire ads at 20% risk instead of 37% — far too often, wasting money. The registry
binds each model to its own threshold. A unit test asserts these constants still match
`meta.json` so they cannot silently drift.

The `exact_pittsburgh` daily threshold is `thr_opt_daily` (0.3681), **not** `thr_opt`
(0.0697); the latter is a zip-day artifact of a spatially-flat model (per the note in
`model_metrics.json`). The daily forecast path uses the daily threshold, which is correct.

## Components

### 1. `ad_providers/eltoro_client.py` — thin REST client (no business logic)
- OAuth2 client-credentials token acquisition + in-memory cache + auto-refresh before expiry.
- Base URL as a single constant.
- Typed methods only for what we need: `get_order_line`, `list_order_lines`,
  `request_review`, `cancel_deployment`, `get_balance`.
- Credentials read from env vars `ELTORO_CLIENT_ID` / `ELTORO_CLIENT_SECRET`
  (optionally loaded from a git-ignored `.env`). Never hardcoded, never committed.
- Fully unit-testable against mocked HTTP; no network in tests.

### 2. `ad_providers/eltoro.py` — implements the existing `AdProvider` interface
- `activate_campaign(tract_id, ...)`: look up the pre-approved `order_line_id` for the
  tract in the mapping file, then enable it via `_set_serving(order_line_id, True)`.
  Returns `{"status": "ok", "campaign_id": order_line_id, ...}` so the existing
  `ad_trigger.py` state machine (cooldown, max-active, expiry/extend) works unchanged.
- `deactivate_campaign(order_line_id)`: `_set_serving(order_line_id, False)`.
- `get_campaign_status` / `list_active_campaigns`: via `get_order_line` / `list_order_lines`.
- **Refuses any tract or order_line_id not present in the mapping file** (defense in depth).
- `_set_serving(order_line_id, serving: bool)`: the single method encapsulating the
  on/off primitive, with a prominent "CONFIRM WITH REP" comment (see Open Question).
- **Never** creates order lines or sets budgets.

### 3. `eltoro_order_lines.json` — mapping file (git-ignored)
Produced at setup. Schema:
```json
{
  "org_id": "…",
  "campaign_id": "…",
  "order_lines": {
    "21157950101": "order-line-id-abc",
    "21157950102": "order-line-id-def"
  }
}
```
- Built by hand from the portal, or via an optional read-only helper `eltoro_discover.py`
  that calls `list_order_lines` for the campaign and matches order lines to tracts by name.
- Tracts absent from `order_lines` are silently skipped — never touched by the daily path.

### 4. `ad_config.py` — cleaned up
- `MODEL_REGISTRY`: maps each model mode → `{coeff_key, threshold}` with provenance comments.
- `MODEL_MODE = "exact_pittsburgh"` (default). `ORI_THRESHOLD = None` → use the model's
  bound threshold; a non-None value is an explicit override.
- `FORECAST_HORIZON_DAYS = 1` (next-day; configurable).
- `MAX_ACTIVE_TRACTS`: a concrete integer cap (not `None`) as a budget safeguard.
- El Toro settings: `AD_PROVIDER`, `ELTORO_ENABLED = False` (kill switch),
  `ELTORO_BASE_URL`, `ELTORO_MAPPING_FILE` path, `ELTORO_ENV` (dev/prod).

### 5. `ad_trigger.py` — guardrail gating
- **Dry-run by default.** A real (spending) run requires BOTH:
  1. `--live` on the command line, AND
  2. `ELTORO_ENABLED = True` in `ad_config.py`.
  Missing either → dry-run; nothing is sent to El Toro.
- Model→threshold binding via the registry (CLI `--threshold` still overrides for a run).
- Pre-flight before any deploy: confirm the token works; optionally check balance.
- Enforce `MAX_ACTIVE_TRACTS` (existing logic).
- Full decision logging to `ad_decisions.log` and state to `ad_state.json` (existing).

## Testing (all runnable before a real key exists)

- **Token:** fetch + auto-refresh against mocked Keycloak; asserts refresh on expiry. No network.
- **Provider on/off:** against a mocked client — asserts correct endpoints are called and
  that unknown tracts / order lines are **refused**.
- **Guardrail gating:** dry-run is default; `--live` alone does not spend; `--live` +
  `ELTORO_ENABLED=True` does (against the mock).
- **Model→threshold binding:** registry thresholds match `meta.json` model_metrics.
- **Mock provider:** existing `mock` provider still supports full end-to-end dry runs today.

## Operator inputs needed later (nothing blocks building the code now)

1. Credential values `ELTORO_CLIENT_ID` / `ELTORO_CLIENT_SECRET` — pasted into `.env`.
2. Rep answer to the Open Question (fills `_set_serving()`).
3. At setup: `org_id`, `campaign_id`, and tract→order-line IDs for the mapping file.

## Out of scope

- Creating order lines / targets / creatives / budgets via API (done by human in the portal).
- Changing the forecast model math or the site.
- Any spend-amount logic in the automated path.
