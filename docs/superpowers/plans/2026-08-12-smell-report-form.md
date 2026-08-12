# Calvert City Smell Report Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mobile-first web form (the El Toro ad landing page) that files smell reports into our own D1 database and forwards them to Smell MyCity's `POST /api/v2/smell_reports` once CREATE Lab issues a `client_token`.

**Architecture:** Static HTML/JS frontend + Cloudflare Pages Functions backend + D1 (SQLite) in one self-contained directory, `smell-report-form/`, inside this repo. All business logic lives in pure modules under `src/` (unit-tested with vitest against an in-memory SQLite fake of the D1 API); `functions/` files are thin HTTP adapters. The local database is the source of truth; forwarding to Smell MyCity is disabled by default and can never lose a report.

**Tech Stack:** Cloudflare Pages + Pages Functions + D1, wrangler, vitest, better-sqlite3 (tests only), vanilla HTML/CSS/JS frontend, Nominatim (OpenStreetMap) for geocoding.

## Global Constraints

- Everything lives under `smell-report-form/` in this repo; it must stay self-contained (own `package.json`) so it can later be pushed to the school's GitHub org or pointed at by Cloudflare Pages with root directory = `smell-report-form`.
- Node 20+. `"type": "module"` — ES modules everywhere.
- Secrets are NEVER committed: `SMC_CLIENT_TOKEN`, `EXPORT_TOKEN`, `RATE_SALT` live in Cloudflare env settings / local `.dev.vars` (gitignored). `.dev.vars.example` documents them.
- `FORWARDING_ENABLED` defaults to `"false"`; nothing is ever sent to Smell MyCity unless it is the string `"true"` AND `SMC_CLIENT_TOKEN` is set. (Same dry-run-by-default guardrail as the El Toro integration.)
- Smell MyCity API parameter names are exactly: `client_token`, `latitude`, `longitude`, `user_hash`, `smell_value`, `smell_description`, `feelings_symptoms`, `additional_comments`, `custom_location`, `custom_time`, `observed_at` (RFC 3339). Do not invent others.
- Never impersonate the mobile app's client token. The endpoint base URL is configurable via `SMC_API_BASE` (CREATE Lab will confirm it when issuing the token).
- Form field copy mirrors Smell MyCity's app: rating labels 1="Just fine!", 2="Barely noticeable", 3="Definitely noticeable", 4="It's getting pretty bad", 5="About as bad as it gets!".
- Region bounding box (generous, covers Calvert City + surrounding area): lat 36.6–37.4, lon −89.0…−87.9.
- Timestamps are stored as ISO 8601 UTC strings (`new Date().toISOString()`), which is valid RFC 3339.
- Run all tests from `smell-report-form/`: `npx vitest run`.
- Commit after every green test cycle; commit messages in imperative mood.

---

### Task 1: Scaffold + validation module

**Files:**
- Create: `smell-report-form/package.json`
- Create: `smell-report-form/.gitignore`
- Create: `smell-report-form/.dev.vars.example`
- Create: `smell-report-form/wrangler.toml`
- Create: `smell-report-form/src/validate.js`
- Test: `smell-report-form/test/validate.test.js`

**Interfaces:**
- Produces: `validateReport(body) -> { ok: true, report } | { ok: false, errors: string[] }` where `report` has keys `smell_value` (int), `latitude`/`longitude` (numbers), `location_method` (`'gps'|'manual'`), `smell_description`/`feelings_symptoms`/`additional_comments`/`user_hash` (string or null). Also exports `REGION` constant.

- [ ] **Step 1: Create scaffold files**

`smell-report-form/package.json`:

```json
{
  "name": "calvert-smell-report",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "dev": "wrangler pages dev"
  },
  "devDependencies": {
    "better-sqlite3": "^11.0.0",
    "vitest": "^2.0.0",
    "wrangler": "^4.0.0"
  }
}
```

`smell-report-form/.gitignore`:

```
node_modules/
.dev.vars
.wrangler/
```

`smell-report-form/.dev.vars.example` (copy to `.dev.vars` locally; real values only in Cloudflare dashboard):

```
SMC_API_BASE=https://api.smellmycity.org
SMC_CLIENT_TOKEN=
FORWARDING_ENABLED=false
EXPORT_TOKEN=pick-a-long-random-string
RATE_SALT=pick-another-long-random-string
```

`smell-report-form/wrangler.toml`:

```toml
name = "calvert-smell-report"
compatibility_date = "2026-08-01"
pages_build_output_dir = "public"

[[d1_databases]]
binding = "DB"
database_name = "smell_reports"
database_id = "REPLACE_WITH_ID_FROM_wrangler_d1_create"
```

Run: `cd smell-report-form && npm install`
Expected: installs cleanly.

- [ ] **Step 2: Write the failing test**

`smell-report-form/test/validate.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { validateReport, REGION } from '../src/validate.js';

const good = () => ({
  smell_value: 4,
  latitude: 37.033,
  longitude: -88.35,
  location_method: 'gps',
  smell_description: 'rotten eggs',
  feelings_symptoms: 'headache',
  additional_comments: '',
  user_hash: 'web-abc123',
});

describe('validateReport', () => {
  it('accepts a complete valid report and normalizes empty strings to null', () => {
    const v = validateReport(good());
    expect(v.ok).toBe(true);
    expect(v.report.smell_value).toBe(4);
    expect(v.report.additional_comments).toBeNull();
    expect(v.report.smell_description).toBe('rotten eggs');
  });

  it('rejects non-object bodies', () => {
    expect(validateReport(null).ok).toBe(false);
    expect(validateReport('hi').ok).toBe(false);
  });

  it('rejects smell_value outside 1-5 or non-integer', () => {
    for (const bad of [0, 6, 2.5, 'high', null, undefined]) {
      const v = validateReport({ ...good(), smell_value: bad });
      expect(v.ok).toBe(false);
      expect(v.errors.join(' ')).toMatch(/smell_value/);
    }
  });

  it('rejects missing or non-numeric coordinates', () => {
    const v = validateReport({ ...good(), latitude: undefined });
    expect(v.ok).toBe(false);
    expect(v.errors.join(' ')).toMatch(/location/i);
  });

  it('rejects coordinates outside the Calvert City region box', () => {
    const pittsburgh = validateReport({ ...good(), latitude: 40.44, longitude: -79.99 });
    expect(pittsburgh.ok).toBe(false);
    expect(pittsburgh.errors.join(' ')).toMatch(/region/i);
    expect(REGION.latMin).toBeLessThan(37.033);
    expect(REGION.latMax).toBeGreaterThan(37.033);
  });

  it('rejects unknown location_method', () => {
    const v = validateReport({ ...good(), location_method: 'ip' });
    expect(v.ok).toBe(false);
  });

  it('rejects over-long text fields', () => {
    const v = validateReport({ ...good(), smell_description: 'x'.repeat(501) });
    expect(v.ok).toBe(false);
  });

  it('accepts missing optional text fields', () => {
    const { smell_description, feelings_symptoms, additional_comments, user_hash, ...min } = good();
    const v = validateReport(min);
    expect(v.ok).toBe(true);
    expect(v.report.smell_description).toBeNull();
    expect(v.report.user_hash).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run test/validate.test.js`
Expected: FAIL — cannot resolve `../src/validate.js`.

- [ ] **Step 4: Write the implementation**

`smell-report-form/src/validate.js`:

```js
// Generous box around Calvert City, KY (~37.033, -88.35) and neighboring towns.
export const REGION = { latMin: 36.6, latMax: 37.4, lonMin: -89.0, lonMax: -87.9 };

const MAX_TEXT = 500;
const TEXT_FIELDS = ['smell_description', 'feelings_symptoms', 'additional_comments'];

export function validateReport(body) {
  if (typeof body !== 'object' || body === null) {
    return { ok: false, errors: ['invalid request body'] };
  }
  const errors = [];

  const sv = body.smell_value;
  if (!Number.isInteger(sv) || sv < 1 || sv > 5) {
    errors.push('smell_value must be an integer from 1 to 5');
  }

  const lat = Number(body.latitude);
  const lon = Number(body.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    errors.push('location is required');
  } else if (lat < REGION.latMin || lat > REGION.latMax || lon < REGION.lonMin || lon > REGION.lonMax) {
    errors.push('location is outside the Calvert City region');
  }

  if (!['gps', 'manual'].includes(body.location_method)) {
    errors.push('location_method must be "gps" or "manual"');
  }

  for (const f of TEXT_FIELDS) {
    if (body[f] != null && (typeof body[f] !== 'string' || body[f].length > MAX_TEXT)) {
      errors.push(`${f} must be a string of at most ${MAX_TEXT} characters`);
    }
  }
  if (body.user_hash != null && (typeof body.user_hash !== 'string' || body.user_hash.length > 100)) {
    errors.push('user_hash must be a string of at most 100 characters');
  }

  if (errors.length) return { ok: false, errors };

  const text = (f) => {
    const t = typeof body[f] === 'string' ? body[f].trim() : '';
    return t.length ? t : null;
  };
  return {
    ok: true,
    report: {
      smell_value: sv,
      latitude: lat,
      longitude: lon,
      location_method: body.location_method,
      smell_description: text('smell_description'),
      feelings_symptoms: text('feelings_symptoms'),
      additional_comments: text('additional_comments'),
      user_hash: body.user_hash || null,
    },
  };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run test/validate.test.js`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add smell-report-form
git commit -m "feat: scaffold smell report form project with report validation"
```

---

### Task 2: Smell MyCity payload builder + forwarder

**Files:**
- Create: `smell-report-form/src/smellmycity.js`
- Test: `smell-report-form/test/smellmycity.test.js`

**Interfaces:**
- Consumes: normalized `report` objects shaped like Task 1's `validateReport(...).report` (plus, for backfill, DB rows that additionally carry `observed_at`).
- Produces:
  - `buildSmcPayload(report, { clientToken, backfill = false }) -> object` (exact Smell MyCity param names)
  - `forwardReport(payload, { apiBase, fetchFn = fetch }) -> Promise<{ ok: boolean, status: number, body: string }>` — never throws.

- [ ] **Step 1: Write the failing test**

`smell-report-form/test/smellmycity.test.js`:

```js
import { describe, it, expect, vi } from 'vitest';
import { buildSmcPayload, forwardReport } from '../src/smellmycity.js';

const report = {
  smell_value: 3,
  latitude: 37.03,
  longitude: -88.35,
  location_method: 'gps',
  smell_description: 'chemical',
  feelings_symptoms: null,
  additional_comments: null,
  user_hash: 'web-xyz',
  observed_at: '2026-08-10T14:05:00.000Z',
};

describe('buildSmcPayload', () => {
  it('maps fields to exact Smell MyCity parameter names, omitting nulls', () => {
    const p = buildSmcPayload(report, { clientToken: 'tok123' });
    expect(p).toEqual({
      client_token: 'tok123',
      latitude: 37.03,
      longitude: -88.35,
      smell_value: 3,
      smell_description: 'chemical',
      user_hash: 'web-xyz',
    });
    expect(p).not.toHaveProperty('feelings_symptoms');
    expect(p).not.toHaveProperty('custom_time');
  });

  it('sets custom_location for manually-entered addresses', () => {
    const p = buildSmcPayload({ ...report, location_method: 'manual' }, { clientToken: 't' });
    expect(p.custom_location).toBe(true);
  });

  it('backfill mode sends custom_time with the original observed_at', () => {
    const p = buildSmcPayload(report, { clientToken: 't', backfill: true });
    expect(p.custom_time).toBe(true);
    expect(p.observed_at).toBe('2026-08-10T14:05:00.000Z');
  });
});

describe('forwardReport', () => {
  it('POSTs JSON to {apiBase}/api/v2/smell_reports and reports success', async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      new Response('{"id":42}', { status: 200 })
    );
    const r = await forwardReport({ client_token: 't' }, { apiBase: 'https://api.example.org', fetchFn });
    expect(fetchFn).toHaveBeenCalledWith('https://api.example.org/api/v2/smell_reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"client_token":"t"}',
    });
    expect(r).toEqual({ ok: true, status: 200, body: '{"id":42}' });
  });

  it('reports HTTP failure without throwing', async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response('nope', { status: 403 }));
    const r = await forwardReport({}, { apiBase: 'https://api.example.org', fetchFn });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(403);
  });

  it('reports network errors without throwing', async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const r = await forwardReport({}, { apiBase: 'https://api.example.org', fetchFn });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(0);
    expect(r.body).toMatch(/ECONNREFUSED/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/smellmycity.test.js`
Expected: FAIL — cannot resolve `../src/smellmycity.js`.

- [ ] **Step 3: Write the implementation**

`smell-report-form/src/smellmycity.js`:

```js
// Parameter names come verbatim from the smell-pittsburgh-rails API wiki.
export function buildSmcPayload(report, { clientToken, backfill = false }) {
  const p = {
    client_token: clientToken,
    latitude: report.latitude,
    longitude: report.longitude,
    smell_value: report.smell_value,
  };
  if (report.smell_description) p.smell_description = report.smell_description;
  if (report.feelings_symptoms) p.feelings_symptoms = report.feelings_symptoms;
  if (report.additional_comments) p.additional_comments = report.additional_comments;
  if (report.user_hash) p.user_hash = report.user_hash;
  if (report.location_method === 'manual') p.custom_location = true;
  if (backfill) {
    p.custom_time = true;
    p.observed_at = report.observed_at;
  }
  return p;
}

export async function forwardReport(payload, { apiBase, fetchFn = fetch }) {
  try {
    const res = await fetchFn(`${apiBase}/api/v2/smell_reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, body: text.slice(0, 1000) };
  } catch (err) {
    return { ok: false, status: 0, body: String(err) };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/smellmycity.test.js`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add smell-report-form/src/smellmycity.js smell-report-form/test/smellmycity.test.js
git commit -m "feat: build and forward Smell MyCity payloads with backfill timestamps"
```

---

### Task 3: D1 schema + database helpers

**Files:**
- Create: `smell-report-form/schema.sql`
- Create: `smell-report-form/src/db.js`
- Create: `smell-report-form/test/fake-d1.js`
- Test: `smell-report-form/test/db.test.js`

**Interfaces:**
- Consumes: a D1-shaped database object (`db.prepare(sql).bind(...args).run()/.all()`).
- Produces (all async, all take `db` first):
  - `insertReport(db, report, { observedAt, ipHash }) -> id`
  - `markForwarded(db, id, responseBody, forwardedAt)`
  - `unforwardedReports(db, limit = 200) -> rows` (each row includes `observed_at`, all report columns, `id`)
  - `allReports(db) -> rows`
  - `recordRateEvent(db, ipHash, nowSecs)`
  - `countRecentByIp(db, ipHash, nowSecs, windowSecs = 3600) -> number`
- Test helper: `makeDb()` in `test/fake-d1.js` returns an in-memory better-sqlite3 database wrapped in the D1 API shape, with `schema.sql` applied.

- [ ] **Step 1: Write schema and the failing test**

`smell-report-form/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  location_method TEXT NOT NULL,
  smell_value INTEGER NOT NULL,
  smell_description TEXT,
  feelings_symptoms TEXT,
  additional_comments TEXT,
  user_hash TEXT,
  ip_hash TEXT,
  forwarded INTEGER NOT NULL DEFAULT 0,
  forward_response TEXT,
  forwarded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_forwarded ON reports(forwarded);

CREATE TABLE IF NOT EXISTS rate_events (
  ip_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_ip_time ON rate_events(ip_hash, created_at);
```

`smell-report-form/test/fake-d1.js`:

```js
import Database from 'better-sqlite3';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const schema = readFileSync(
  fileURLToPath(new URL('../schema.sql', import.meta.url)),
  'utf8'
);

// Minimal in-memory stand-in for Cloudflare D1's prepare/bind/run/all API.
export function makeDb() {
  const sqlite = new Database(':memory:');
  sqlite.exec(schema);
  return {
    prepare(sql) {
      let params = [];
      const stmt = {
        bind(...args) { params = args; return stmt; },
        run() {
          const info = sqlite.prepare(sql).run(...params);
          return Promise.resolve({ meta: { last_row_id: Number(info.lastInsertRowid) } });
        },
        all() {
          const results = sqlite.prepare(sql).all(...params);
          return Promise.resolve({ results });
        },
      };
      return stmt;
    },
  };
}
```

`smell-report-form/test/db.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { makeDb } from './fake-d1.js';
import {
  insertReport, markForwarded, unforwardedReports, allReports,
  recordRateEvent, countRecentByIp,
} from '../src/db.js';

const report = {
  smell_value: 5,
  latitude: 37.03,
  longitude: -88.35,
  location_method: 'gps',
  smell_description: 'sulfur',
  feelings_symptoms: 'eye irritation',
  additional_comments: null,
  user_hash: 'web-abc',
};

describe('reports table helpers', () => {
  it('inserts a report and returns its id', async () => {
    const db = makeDb();
    const id = await insertReport(db, report, { observedAt: '2026-08-12T01:02:03.000Z', ipHash: 'h1' });
    expect(id).toBe(1);
    const rows = await allReports(db);
    expect(rows).toHaveLength(1);
    expect(rows[0].observed_at).toBe('2026-08-12T01:02:03.000Z');
    expect(rows[0].forwarded).toBe(0);
    expect(rows[0].smell_value).toBe(5);
  });

  it('lists only unforwarded reports and marks them forwarded', async () => {
    const db = makeDb();
    const a = await insertReport(db, report, { observedAt: '2026-08-12T01:00:00.000Z', ipHash: 'h' });
    const b = await insertReport(db, report, { observedAt: '2026-08-12T02:00:00.000Z', ipHash: 'h' });
    await markForwarded(db, a, '{"id":9}', '2026-08-12T03:00:00.000Z');
    const pending = await unforwardedReports(db);
    expect(pending.map((r) => r.id)).toEqual([b]);
    const all = await allReports(db);
    expect(all.find((r) => r.id === a).forward_response).toBe('{"id":9}');
    expect(all.find((r) => r.id === a).forwarded_at).toBe('2026-08-12T03:00:00.000Z');
  });
});

describe('rate limiting helpers', () => {
  it('counts only recent events for the given ip hash', async () => {
    const db = makeDb();
    const now = 10_000;
    await recordRateEvent(db, 'ipA', now - 3000);   // inside 1h window
    await recordRateEvent(db, 'ipA', now - 3700);   // outside 1h window
    await recordRateEvent(db, 'ipB', now - 10);     // other ip
    expect(await countRecentByIp(db, 'ipA', now)).toBe(1);
    expect(await countRecentByIp(db, 'ipB', now)).toBe(1);
    expect(await countRecentByIp(db, 'ipC', now)).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/db.test.js`
Expected: FAIL — cannot resolve `../src/db.js`.

- [ ] **Step 3: Write the implementation**

`smell-report-form/src/db.js`:

```js
export async function insertReport(db, report, { observedAt, ipHash }) {
  const res = await db
    .prepare(
      `INSERT INTO reports (observed_at, latitude, longitude, location_method, smell_value,
         smell_description, feelings_symptoms, additional_comments, user_hash, ip_hash)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      observedAt, report.latitude, report.longitude, report.location_method,
      report.smell_value, report.smell_description, report.feelings_symptoms,
      report.additional_comments, report.user_hash, ipHash
    )
    .run();
  return res.meta.last_row_id;
}

export async function markForwarded(db, id, responseBody, forwardedAt) {
  await db
    .prepare(`UPDATE reports SET forwarded = 1, forward_response = ?, forwarded_at = ? WHERE id = ?`)
    .bind(responseBody, forwardedAt, id)
    .run();
}

export async function unforwardedReports(db, limit = 200) {
  const { results } = await db
    .prepare(`SELECT * FROM reports WHERE forwarded = 0 ORDER BY id LIMIT ?`)
    .bind(limit)
    .all();
  return results;
}

export async function allReports(db) {
  const { results } = await db.prepare(`SELECT * FROM reports ORDER BY id`).all();
  return results;
}

export async function recordRateEvent(db, ipHash, nowSecs) {
  await db
    .prepare(`INSERT INTO rate_events (ip_hash, created_at) VALUES (?, ?)`)
    .bind(ipHash, nowSecs)
    .run();
}

export async function countRecentByIp(db, ipHash, nowSecs, windowSecs = 3600) {
  const { results } = await db
    .prepare(`SELECT COUNT(*) AS n FROM rate_events WHERE ip_hash = ? AND created_at > ?`)
    .bind(ipHash, nowSecs - windowSecs)
    .all();
  return results[0].n;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/db.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add smell-report-form/schema.sql smell-report-form/src/db.js smell-report-form/test/fake-d1.js smell-report-form/test/db.test.js
git commit -m "feat: add D1 schema and database helpers for reports and rate events"
```

---

### Task 4: POST /api/report handler

**Files:**
- Create: `smell-report-form/functions/api/report.js`
- Test: `smell-report-form/test/report.test.js`

**Interfaces:**
- Consumes: `validateReport` (Task 1), `buildSmcPayload`/`forwardReport` (Task 2), all db helpers (Task 3).
- Produces:
  - `handleReport({ body, ip, env, now, fetchFn }) -> Promise<{ status, json }>` — pure of HTTP, fully testable.
  - `hashIp(ip, salt) -> Promise<hex string>` (SHA-256 via WebCrypto).
  - `onRequestPost(context)` — the Pages Functions adapter (thin, not unit-tested).
- `env` fields used: `DB`, `RATE_SALT`, `FORWARDING_ENABLED`, `SMC_CLIENT_TOKEN`, `SMC_API_BASE`.

- [ ] **Step 1: Write the failing test**

`smell-report-form/test/report.test.js`:

```js
import { describe, it, expect, vi } from 'vitest';
import { makeDb } from './fake-d1.js';
import { handleReport, hashIp } from '../functions/api/report.js';
import { allReports } from '../src/db.js';

const NOW = new Date('2026-08-12T15:30:00.000Z');

const body = () => ({
  smell_value: 4,
  latitude: 37.033,
  longitude: -88.35,
  location_method: 'gps',
  smell_description: 'rotten eggs',
});

function env(overrides = {}) {
  return {
    DB: makeDb(),
    RATE_SALT: 'salt',
    FORWARDING_ENABLED: 'false',
    SMC_CLIENT_TOKEN: '',
    SMC_API_BASE: 'https://api.example.org',
    ...overrides,
  };
}

describe('hashIp', () => {
  it('is deterministic and salt-dependent', async () => {
    expect(await hashIp('1.2.3.4', 's')).toBe(await hashIp('1.2.3.4', 's'));
    expect(await hashIp('1.2.3.4', 's')).not.toBe(await hashIp('1.2.3.4', 't'));
    expect(await hashIp('1.2.3.4', 's')).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe('handleReport', () => {
  it('stores a valid report and returns its id without forwarding when disabled', async () => {
    const e = env();
    const fetchFn = vi.fn();
    const r = await handleReport({ body: body(), ip: '1.2.3.4', env: e, now: NOW, fetchFn });
    expect(r.status).toBe(200);
    expect(r.json.ok).toBe(true);
    const rows = await allReports(e.DB);
    expect(rows).toHaveLength(1);
    expect(rows[0].observed_at).toBe('2026-08-12T15:30:00.000Z');
    expect(rows[0].forwarded).toBe(0);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('silently accepts honeypot submissions without storing anything', async () => {
    const e = env();
    const r = await handleReport({ body: { ...body(), website: 'spam.example' }, ip: '1.2.3.4', env: e, now: NOW, fetchFn: vi.fn() });
    expect(r.status).toBe(200);
    expect(r.json.ok).toBe(true);
    expect(await allReports(e.DB)).toHaveLength(0);
  });

  it('rejects invalid reports with 400 and stores nothing', async () => {
    const e = env();
    const r = await handleReport({ body: { ...body(), smell_value: 9 }, ip: '1.2.3.4', env: e, now: NOW, fetchFn: vi.fn() });
    expect(r.status).toBe(400);
    expect(r.json.errors.join(' ')).toMatch(/smell_value/);
    expect(await allReports(e.DB)).toHaveLength(0);
  });

  it('rate limits the 6th submission in an hour from one ip', async () => {
    const e = env();
    for (let i = 0; i < 5; i++) {
      const r = await handleReport({ body: body(), ip: '9.9.9.9', env: e, now: NOW, fetchFn: vi.fn() });
      expect(r.status).toBe(200);
    }
    const r6 = await handleReport({ body: body(), ip: '9.9.9.9', env: e, now: NOW, fetchFn: vi.fn() });
    expect(r6.status).toBe(429);
    const other = await handleReport({ body: body(), ip: '8.8.8.8', env: e, now: NOW, fetchFn: vi.fn() });
    expect(other.status).toBe(200);
  });

  it('forwards immediately when enabled and marks the row forwarded', async () => {
    const e = env({ FORWARDING_ENABLED: 'true', SMC_CLIENT_TOKEN: 'tok' });
    const fetchFn = vi.fn().mockResolvedValue(new Response('{"id":7}', { status: 200 }));
    const r = await handleReport({ body: body(), ip: '1.2.3.4', env: e, now: NOW, fetchFn });
    expect(r.status).toBe(200);
    const [url, opts] = fetchFn.mock.calls[0];
    expect(url).toBe('https://api.example.org/api/v2/smell_reports');
    const sent = JSON.parse(opts.body);
    expect(sent.client_token).toBe('tok');
    expect(sent.custom_time).toBeUndefined(); // live report: server time is correct
    const rows = await allReports(e.DB);
    expect(rows[0].forwarded).toBe(1);
  });

  it('still succeeds for the user when forwarding fails, leaving the row unforwarded', async () => {
    const e = env({ FORWARDING_ENABLED: 'true', SMC_CLIENT_TOKEN: 'tok' });
    const fetchFn = vi.fn().mockRejectedValue(new Error('down'));
    const r = await handleReport({ body: body(), ip: '1.2.3.4', env: e, now: NOW, fetchFn });
    expect(r.status).toBe(200);
    expect(r.json.ok).toBe(true);
    const rows = await allReports(e.DB);
    expect(rows[0].forwarded).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/report.test.js`
Expected: FAIL — cannot resolve `../functions/api/report.js`.

- [ ] **Step 3: Write the implementation**

`smell-report-form/functions/api/report.js`:

```js
import { validateReport } from '../../src/validate.js';
import { buildSmcPayload, forwardReport } from '../../src/smellmycity.js';
import {
  insertReport, markForwarded, recordRateEvent, countRecentByIp,
} from '../../src/db.js';

const RATE_LIMIT_PER_HOUR = 5;

export async function hashIp(ip, salt) {
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function handleReport({ body, ip, env, now, fetchFn }) {
  // Honeypot: bots fill every field. Pretend success, store nothing.
  if (body && typeof body === 'object' && body.website) {
    return { status: 200, json: { ok: true } };
  }

  const ipHash = await hashIp(ip, env.RATE_SALT || '');
  const nowSecs = Math.floor(now.getTime() / 1000);
  if ((await countRecentByIp(env.DB, ipHash, nowSecs)) >= RATE_LIMIT_PER_HOUR) {
    return {
      status: 429,
      json: { ok: false, errors: ['Too many reports from this connection — please try again later.'] },
    };
  }

  const v = validateReport(body);
  if (!v.ok) return { status: 400, json: { ok: false, errors: v.errors } };

  await recordRateEvent(env.DB, ipHash, nowSecs);
  const observedAt = now.toISOString();
  const id = await insertReport(env.DB, v.report, { observedAt, ipHash });

  if (env.FORWARDING_ENABLED === 'true' && env.SMC_CLIENT_TOKEN) {
    const payload = buildSmcPayload(v.report, { clientToken: env.SMC_CLIENT_TOKEN });
    const result = await forwardReport(payload, { apiBase: env.SMC_API_BASE, fetchFn });
    if (result.ok) {
      await markForwarded(env.DB, id, result.body, now.toISOString());
    }
    // On failure the row stays forwarded=0; the backfill endpoint retries it.
  }

  return { status: 200, json: { ok: true, id } };
}

export async function onRequestPost({ request, env }) {
  let body = null;
  try { body = await request.json(); } catch { /* handled by validation */ }
  const ip = request.headers.get('CF-Connecting-IP') || '0.0.0.0';
  const result = await handleReport({ body, ip, env, now: new Date(), fetchFn: fetch });
  return new Response(JSON.stringify(result.json), {
    status: result.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/report.test.js`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the whole suite**

Run: `npx vitest run`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add smell-report-form/functions/api/report.js smell-report-form/test/report.test.js
git commit -m "feat: add report submission endpoint with honeypot, rate limit, optional forward"
```

---

### Task 5: CSV export endpoint

**Files:**
- Create: `smell-report-form/src/csv.js`
- Create: `smell-report-form/functions/api/export.js`
- Test: `smell-report-form/test/csv.test.js`

**Interfaces:**
- Consumes: `allReports` (Task 3).
- Produces:
  - `toCsv(rows) -> string` with header row; columns: `id, observed_at, latitude, longitude, location_method, smell_value, smell_description, feelings_symptoms, additional_comments, user_hash, forwarded, forwarded_at`.
  - `handleExport({ authHeader, env }) -> Promise<{ status, body, contentType }>` — requires `Authorization: Bearer <EXPORT_TOKEN>`.
  - `onRequestGet(context)` adapter.

- [ ] **Step 1: Write the failing test**

`smell-report-form/test/csv.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { toCsv } from '../src/csv.js';
import { handleExport } from '../functions/api/export.js';
import { makeDb } from './fake-d1.js';
import { insertReport } from '../src/db.js';

describe('toCsv', () => {
  it('emits a header even with no rows', () => {
    expect(toCsv([])).toBe(
      'id,observed_at,latitude,longitude,location_method,smell_value,smell_description,feelings_symptoms,additional_comments,user_hash,forwarded,forwarded_at\n'
    );
  });

  it('escapes quotes, commas, and newlines; renders null as empty', () => {
    const row = {
      id: 1, observed_at: '2026-08-12T00:00:00.000Z', latitude: 37, longitude: -88.3,
      location_method: 'gps', smell_value: 2,
      smell_description: 'burnt, "plastic"\nsmell', feelings_symptoms: null,
      additional_comments: null, user_hash: null, forwarded: 0, forwarded_at: null,
    };
    const lines = toCsv([row]).split('\n');
    expect(lines[1] + '\n' + lines[2]).toContain('"burnt, ""plastic""\nsmell"');
    expect(toCsv([row])).toContain(',gps,2,');
  });
});

describe('handleExport', () => {
  it('rejects missing or wrong tokens', async () => {
    const env = { DB: makeDb(), EXPORT_TOKEN: 'secret' };
    expect((await handleExport({ authHeader: null, env })).status).toBe(401);
    expect((await handleExport({ authHeader: 'Bearer wrong', env })).status).toBe(401);
  });

  it('rejects everything when EXPORT_TOKEN is unset (fails closed)', async () => {
    const env = { DB: makeDb(), EXPORT_TOKEN: '' };
    expect((await handleExport({ authHeader: 'Bearer ', env })).status).toBe(401);
  });

  it('returns CSV of all reports with the right token', async () => {
    const env = { DB: makeDb(), EXPORT_TOKEN: 'secret' };
    await insertReport(env.DB, {
      smell_value: 3, latitude: 37.03, longitude: -88.35, location_method: 'gps',
      smell_description: 'sulfur', feelings_symptoms: null, additional_comments: null, user_hash: null,
    }, { observedAt: '2026-08-12T00:00:00.000Z', ipHash: 'h' });
    const r = await handleExport({ authHeader: 'Bearer secret', env });
    expect(r.status).toBe(200);
    expect(r.contentType).toBe('text/csv');
    expect(r.body.split('\n')[1]).toContain('sulfur');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/csv.test.js`
Expected: FAIL — cannot resolve `../src/csv.js`.

- [ ] **Step 3: Write the implementation**

`smell-report-form/src/csv.js`:

```js
const COLUMNS = [
  'id', 'observed_at', 'latitude', 'longitude', 'location_method', 'smell_value',
  'smell_description', 'feelings_symptoms', 'additional_comments', 'user_hash',
  'forwarded', 'forwarded_at',
];

function esc(v) {
  if (v === null || v === undefined) return '';
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

export function toCsv(rows) {
  const lines = [COLUMNS.join(',')];
  for (const r of rows) lines.push(COLUMNS.map((c) => esc(r[c])).join(','));
  return lines.join('\n') + '\n';
}
```

`smell-report-form/functions/api/export.js`:

```js
import { toCsv } from '../../src/csv.js';
import { allReports } from '../../src/db.js';

export async function handleExport({ authHeader, env }) {
  if (!env.EXPORT_TOKEN || authHeader !== `Bearer ${env.EXPORT_TOKEN}`) {
    return { status: 401, body: 'unauthorized', contentType: 'text/plain' };
  }
  const rows = await allReports(env.DB);
  return { status: 200, body: toCsv(rows), contentType: 'text/csv' };
}

export async function onRequestGet({ request, env }) {
  const r = await handleExport({ authHeader: request.headers.get('Authorization'), env });
  return new Response(r.body, { status: r.status, headers: { 'Content-Type': r.contentType } });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/csv.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add smell-report-form/src/csv.js smell-report-form/functions/api/export.js smell-report-form/test/csv.test.js
git commit -m "feat: add token-protected CSV export of stored reports"
```

---

### Task 6: Backfill endpoint

**Files:**
- Create: `smell-report-form/functions/api/backfill.js`
- Test: `smell-report-form/test/backfill.test.js`

**Interfaces:**
- Consumes: `buildSmcPayload`/`forwardReport` (Task 2), `unforwardedReports`/`markForwarded` (Task 3). DB rows carry `observed_at` and `location_method`, so `buildSmcPayload(row, { clientToken, backfill: true })` works directly on them.
- Produces:
  - `handleBackfill({ authHeader, env, now, fetchFn }) -> Promise<{ status, json }>` where success json is `{ ok: true, sent, failed, remaining }`.
  - `onRequestPost(context)` adapter.
- Stops after 3 consecutive failures (so a bad token doesn't hammer their API 200 times).

- [ ] **Step 1: Write the failing test**

`smell-report-form/test/backfill.test.js`:

```js
import { describe, it, expect, vi } from 'vitest';
import { makeDb } from './fake-d1.js';
import { insertReport, allReports } from '../src/db.js';
import { handleBackfill } from '../functions/api/backfill.js';

const NOW = new Date('2026-09-01T12:00:00.000Z');

async function seed(db, n) {
  for (let i = 0; i < n; i++) {
    await insertReport(db, {
      smell_value: 3, latitude: 37.03, longitude: -88.35, location_method: 'gps',
      smell_description: `report ${i}`, feelings_symptoms: null,
      additional_comments: null, user_hash: null,
    }, { observedAt: `2026-08-1${i}T10:00:00.000Z`, ipHash: 'h' });
  }
}

function env(db, overrides = {}) {
  return {
    DB: db, EXPORT_TOKEN: 'secret', FORWARDING_ENABLED: 'true',
    SMC_CLIENT_TOKEN: 'tok', SMC_API_BASE: 'https://api.example.org', ...overrides,
  };
}

describe('handleBackfill', () => {
  it('requires the export token', async () => {
    const r = await handleBackfill({ authHeader: 'Bearer wrong', env: env(makeDb()), now: NOW, fetchFn: vi.fn() });
    expect(r.status).toBe(401);
  });

  it('refuses to run when forwarding is disabled or token missing', async () => {
    const r = await handleBackfill({
      authHeader: 'Bearer secret',
      env: env(makeDb(), { FORWARDING_ENABLED: 'false' }),
      now: NOW, fetchFn: vi.fn(),
    });
    expect(r.status).toBe(409);
  });

  it('forwards each pending report with custom_time and its original observed_at', async () => {
    const db = makeDb();
    await seed(db, 3);
    const fetchFn = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }));
    const r = await handleBackfill({ authHeader: 'Bearer secret', env: env(db), now: NOW, fetchFn });
    expect(r.json).toEqual({ ok: true, sent: 3, failed: 0, remaining: 0 });
    const sentBodies = fetchFn.mock.calls.map(([, opts]) => JSON.parse(opts.body));
    expect(sentBodies[0].custom_time).toBe(true);
    expect(sentBodies[0].observed_at).toBe('2026-08-10T10:00:00.000Z');
    expect(sentBodies[2].observed_at).toBe('2026-08-12T10:00:00.000Z');
    const rows = await allReports(db);
    expect(rows.every((row) => row.forwarded === 1)).toBe(true);
  });

  it('stops after 3 consecutive failures and reports what remains', async () => {
    const db = makeDb();
    await seed(db, 5);
    const fetchFn = vi.fn().mockResolvedValue(new Response('denied', { status: 403 }));
    const r = await handleBackfill({ authHeader: 'Bearer secret', env: env(db), now: NOW, fetchFn });
    expect(fetchFn).toHaveBeenCalledTimes(3);
    expect(r.json.sent).toBe(0);
    expect(r.json.failed).toBe(3);
    expect(r.json.remaining).toBe(5);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/backfill.test.js`
Expected: FAIL — cannot resolve `../functions/api/backfill.js`.

- [ ] **Step 3: Write the implementation**

`smell-report-form/functions/api/backfill.js`:

```js
import { buildSmcPayload, forwardReport } from '../../src/smellmycity.js';
import { unforwardedReports, markForwarded } from '../../src/db.js';

const MAX_CONSECUTIVE_FAILURES = 3;

export async function handleBackfill({ authHeader, env, now, fetchFn }) {
  if (!env.EXPORT_TOKEN || authHeader !== `Bearer ${env.EXPORT_TOKEN}`) {
    return { status: 401, json: { ok: false, errors: ['unauthorized'] } };
  }
  if (env.FORWARDING_ENABLED !== 'true' || !env.SMC_CLIENT_TOKEN) {
    return { status: 409, json: { ok: false, errors: ['forwarding is not enabled'] } };
  }

  const pending = await unforwardedReports(env.DB);
  let sent = 0;
  let failed = 0;
  let consecutive = 0;

  for (const row of pending) {
    const payload = buildSmcPayload(row, { clientToken: env.SMC_CLIENT_TOKEN, backfill: true });
    const result = await forwardReport(payload, { apiBase: env.SMC_API_BASE, fetchFn });
    if (result.ok) {
      await markForwarded(env.DB, row.id, result.body, now.toISOString());
      sent++;
      consecutive = 0;
    } else {
      failed++;
      if (++consecutive >= MAX_CONSECUTIVE_FAILURES) break;
    }
  }

  return { status: 200, json: { ok: true, sent, failed, remaining: pending.length - sent } };
}

export async function onRequestPost({ request, env }) {
  const r = await handleBackfill({
    authHeader: request.headers.get('Authorization'),
    env, now: new Date(), fetchFn: fetch,
  });
  return new Response(JSON.stringify(r.json), {
    status: r.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/backfill.test.js`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the whole suite**

Run: `npx vitest run`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add smell-report-form/functions/api/backfill.js smell-report-form/test/backfill.test.js
git commit -m "feat: add backfill endpoint forwarding stored reports with original timestamps"
```

---

### Task 7: Frontend form

**Files:**
- Create: `smell-report-form/public/form-logic.js` (pure helpers — unit-tested)
- Create: `smell-report-form/public/index.html`
- Create: `smell-report-form/public/style.css`
- Create: `smell-report-form/public/app.js` (DOM glue — exercised in Task 8's end-to-end run)
- Test: `smell-report-form/test/form-logic.test.js`

**Interfaces:**
- Consumes: `POST /api/report` (Task 4) — sends JSON with keys `smell_value`, `latitude`, `longitude`, `location_method`, `smell_description`, `feelings_symptoms`, `additional_comments`, `user_hash`, `website` (honeypot, empty for humans).
- Produces (from `form-logic.js`):
  - `RATING_LABELS: { 1..5: string }`
  - `nominatimReverseUrl(lat, lon) -> string`, `nominatimSearchUrl(address) -> string`
  - `displayAddress(nominatimJson) -> string` (short human-readable place line)
  - `parseSearchResult(nominatimJson) -> { latitude, longitude, display } | null`
  - `getOrCreateUserHash(storage) -> string` (persistent `web-<uuid>` in localStorage)
  - `buildSubmission(state) -> object` (the exact POST body)

- [ ] **Step 1: Write the failing test**

`smell-report-form/test/form-logic.test.js`:

```js
import { describe, it, expect } from 'vitest';
import {
  RATING_LABELS, nominatimReverseUrl, nominatimSearchUrl,
  displayAddress, parseSearchResult, getOrCreateUserHash, buildSubmission,
} from '../public/form-logic.js';

describe('RATING_LABELS', () => {
  it('uses Smell MyCity wording for 1 and 5', () => {
    expect(RATING_LABELS[1]).toBe('Just fine!');
    expect(RATING_LABELS[5]).toBe('About as bad as it gets!');
    expect(Object.keys(RATING_LABELS)).toHaveLength(5);
  });
});

describe('nominatim urls', () => {
  it('builds reverse and search urls with encoding', () => {
    expect(nominatimReverseUrl(37.03, -88.35)).toBe(
      'https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=37.03&lon=-88.35'
    );
    expect(nominatimSearchUrl('101 Main St, Calvert City KY')).toBe(
      'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=101%20Main%20St%2C%20Calvert%20City%20KY'
    );
  });
});

describe('displayAddress', () => {
  it('prefers road + town, falls back to display_name', () => {
    expect(displayAddress({ address: { road: '5th Ave', town: 'Calvert City' } }))
      .toBe('near 5th Ave, Calvert City');
    expect(displayAddress({ display_name: 'Calvert City, Marshall County, Kentucky' }))
      .toBe('near Calvert City, Marshall County, Kentucky');
    expect(displayAddress({})).toBe('at your detected location');
  });
});

describe('parseSearchResult', () => {
  it('extracts coordinates from the first result', () => {
    const r = parseSearchResult([{ lat: '37.01', lon: '-88.30', display_name: 'Main St' }]);
    expect(r).toEqual({ latitude: 37.01, longitude: -88.3, display: 'Main St' });
  });
  it('returns null for empty results', () => {
    expect(parseSearchResult([])).toBeNull();
  });
});

describe('getOrCreateUserHash', () => {
  it('creates once, then reuses', () => {
    const store = new Map();
    const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
    const h1 = getOrCreateUserHash(storage);
    const h2 = getOrCreateUserHash(storage);
    expect(h1).toMatch(/^web-[0-9a-f-]{36}$/);
    expect(h2).toBe(h1);
  });
});

describe('buildSubmission', () => {
  it('assembles the exact POST body with an empty honeypot', () => {
    const body = buildSubmission({
      rating: 4,
      latitude: 37.03,
      longitude: -88.35,
      locationMethod: 'manual',
      description: ' rotten eggs ',
      symptoms: '',
      comments: 'near the plant',
      userHash: 'web-abc',
    });
    expect(body).toEqual({
      smell_value: 4,
      latitude: 37.03,
      longitude: -88.35,
      location_method: 'manual',
      smell_description: 'rotten eggs',
      feelings_symptoms: '',
      additional_comments: 'near the plant',
      user_hash: 'web-abc',
      website: '',
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/form-logic.test.js`
Expected: FAIL — cannot resolve `../public/form-logic.js`.

- [ ] **Step 3: Write the pure helpers**

`smell-report-form/public/form-logic.js`:

```js
export const RATING_LABELS = {
  1: 'Just fine!',
  2: 'Barely noticeable',
  3: 'Definitely noticeable',
  4: "It's getting pretty bad",
  5: 'About as bad as it gets!',
};

export function nominatimReverseUrl(lat, lon) {
  return `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}`;
}

export function nominatimSearchUrl(address) {
  return `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(address)}`;
}

export function displayAddress(json) {
  const a = json.address || {};
  const place = a.town || a.city || a.village || a.hamlet || '';
  if (a.road && place) return `near ${a.road}, ${place}`;
  if (json.display_name) return `near ${json.display_name}`;
  return 'at your detected location';
}

export function parseSearchResult(results) {
  if (!Array.isArray(results) || results.length === 0) return null;
  const r = results[0];
  return { latitude: Number(r.lat), longitude: Number(r.lon), display: r.display_name };
}

export function getOrCreateUserHash(storage) {
  let h = storage.getItem('smell_user_hash');
  if (!h) {
    h = `web-${crypto.randomUUID()}`;
    storage.setItem('smell_user_hash', h);
  }
  return h;
}

export function buildSubmission(state) {
  return {
    smell_value: state.rating,
    latitude: state.latitude,
    longitude: state.longitude,
    location_method: state.locationMethod,
    smell_description: state.description.trim(),
    feelings_symptoms: state.symptoms.trim(),
    additional_comments: state.comments.trim(),
    user_hash: state.userHash,
    website: '', // honeypot — humans never see or fill this
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/form-logic.test.js`
Expected: PASS (7 tests).

- [ ] **Step 5: Write the page, styles, and DOM glue**

`smell-report-form/public/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Report an Odor — Calvert City</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main>
    <h1>Smell something in Calvert City?</h1>
    <p class="tagline">Report it in 30 seconds. No app needed. Reports help track local air quality.</p>

    <form id="report-form" autocomplete="off">
      <fieldset>
        <legend>How bad is the smell right now?</legend>
        <div id="rating-buttons" role="radiogroup" aria-label="Smell rating"></div>
      </fieldset>

      <label for="description">What does it smell like? <span class="hint">(optional — e.g. rotten eggs, chemical)</span></label>
      <input type="text" id="description" maxlength="500">

      <label for="symptoms">Any symptoms? <span class="hint">(optional — e.g. headache, eye irritation)</span></label>
      <input type="text" id="symptoms" maxlength="500">

      <label for="comments">Anything else? <span class="hint">(optional)</span></label>
      <textarea id="comments" rows="2" maxlength="500"></textarea>

      <!-- Honeypot: hidden from humans, tempting to bots -->
      <div class="hp" aria-hidden="true">
        <label for="website">Website</label>
        <input type="text" id="website" name="website" tabindex="-1">
      </div>

      <fieldset id="location-section">
        <legend>Where are you?</legend>
        <button type="button" id="use-location">Use my location</button>
        <p id="location-status" role="status"></p>
        <div id="location-confirm" hidden>
          <p id="detected-address"></p>
          <button type="button" id="location-yes">Yes, that's right</button>
          <button type="button" id="location-no">No, let me type my address</button>
        </div>
        <div id="manual-address" hidden>
          <label for="address">Street address</label>
          <input type="text" id="address" placeholder="101 Main St, Calvert City, KY">
          <button type="button" id="find-address">Find address</button>
        </div>
      </fieldset>

      <button type="submit" id="submit" disabled>Submit report</button>
      <p id="form-error" role="alert" hidden></p>
      <p class="privacy">
        Your report may appear on the public
        <a href="https://smellmycity.org" target="_blank" rel="noopener">Smell MyCity</a> map
        at an approximate location (shifted about a tenth of a mile to protect your privacy).
        Your exact location is used only for air-quality analysis and is never published.
      </p>
    </form>

    <section id="thanks" hidden>
      <h2>Thank you — your report is in.</h2>
      <p>It's recorded with today's date and time and will help track odor problems in Calvert City.</p>
      <button type="button" id="report-again">Report another smell</button>
    </section>
  </main>
  <script type="module" src="app.js"></script>
</body>
</html>
```

`smell-report-form/public/style.css`:

```css
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0; padding: 1rem; background: #f5f7f6; color: #1c2321;
  line-height: 1.45;
}
main { max-width: 28rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0.5rem 0; }
.tagline { margin-top: 0; color: #4a5551; }
form, #thanks { background: #fff; border-radius: 12px; padding: 1rem; box-shadow: 0 1px 4px rgb(0 0 0 / 0.08); }
fieldset { border: none; padding: 0; margin: 0 0 1rem; }
legend { font-weight: 600; padding: 0; margin-bottom: 0.5rem; }
label { display: block; font-weight: 600; margin: 0.75rem 0 0.25rem; }
.hint { font-weight: 400; color: #6a7570; font-size: 0.85rem; }
input[type="text"], textarea {
  width: 100%; padding: 0.6rem; border: 1px solid #c5cec9; border-radius: 8px; font-size: 1rem;
}
#rating-buttons { display: grid; gap: 0.4rem; }
#rating-buttons button {
  padding: 0.7rem; border: 1px solid #c5cec9; border-radius: 8px; background: #fff;
  font-size: 1rem; text-align: left; cursor: pointer;
}
#rating-buttons button[aria-checked="true"] { border-color: #1e6e50; background: #e6f2ec; font-weight: 600; }
button { font: inherit; }
#use-location, #find-address, #location-yes, #location-no, #report-again {
  margin-top: 0.5rem; padding: 0.6rem 1rem; border: 1px solid #1e6e50; border-radius: 8px;
  background: #fff; color: #1e6e50; cursor: pointer;
}
#submit {
  width: 100%; margin-top: 1rem; padding: 0.9rem; border: none; border-radius: 8px;
  background: #1e6e50; color: #fff; font-size: 1.1rem; font-weight: 600; cursor: pointer;
}
#submit:disabled { background: #9db5aa; cursor: not-allowed; }
#form-error { color: #a3242a; font-weight: 600; }
.privacy { font-size: 0.8rem; color: #6a7570; margin-top: 1rem; }
.hp { position: absolute; left: -9999px; top: -9999px; }
```

`smell-report-form/public/app.js`:

```js
import {
  RATING_LABELS, nominatimReverseUrl, nominatimSearchUrl,
  displayAddress, parseSearchResult, getOrCreateUserHash, buildSubmission,
} from './form-logic.js';

const state = {
  rating: null, latitude: null, longitude: null, locationMethod: null,
  description: '', symptoms: '', comments: '',
  userHash: getOrCreateUserHash(localStorage),
};

const $ = (id) => document.getElementById(id);

// Rating buttons
const ratingBox = $('rating-buttons');
for (const [value, label] of Object.entries(RATING_LABELS)) {
  const b = document.createElement('button');
  b.type = 'button';
  b.setAttribute('role', 'radio');
  b.setAttribute('aria-checked', 'false');
  b.textContent = `${value} — ${label}`;
  b.addEventListener('click', () => {
    state.rating = Number(value);
    for (const other of ratingBox.children) other.setAttribute('aria-checked', 'false');
    b.setAttribute('aria-checked', 'true');
    refreshSubmit();
  });
  ratingBox.append(b);
}

function refreshSubmit() {
  $('submit').disabled = !(state.rating && state.latitude !== null);
}

function setLocation(lat, lon, method, statusText) {
  state.latitude = lat;
  state.longitude = lon;
  state.locationMethod = method;
  $('location-status').textContent = statusText;
  refreshSubmit();
}

// GPS flow with "Is this right?" confirmation
$('use-location').addEventListener('click', () => {
  $('location-status').textContent = 'Locating…';
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const { latitude, longitude } = pos.coords;
      let addressLine = 'at your detected location';
      try {
        const res = await fetch(nominatimReverseUrl(latitude, longitude));
        addressLine = displayAddress(await res.json());
      } catch { /* confirmation still works without an address line */ }
      $('detected-address').textContent = `It looks like you're ${addressLine}. Is that right?`;
      $('location-confirm').hidden = false;
      $('location-status').textContent = '';
      $('location-yes').onclick = () => {
        $('location-confirm').hidden = true;
        setLocation(latitude, longitude, 'gps', `Location set (${addressLine}).`);
      };
      $('location-no').onclick = () => {
        $('location-confirm').hidden = true;
        $('manual-address').hidden = false;
      };
    },
    () => {
      $('location-status').textContent = "No problem — type your address instead.";
      $('manual-address').hidden = false;
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
});

// Manual address flow
$('find-address').addEventListener('click', async () => {
  const q = $('address').value.trim();
  if (!q) return;
  $('location-status').textContent = 'Looking up address…';
  try {
    const res = await fetch(nominatimSearchUrl(q));
    const found = parseSearchResult(await res.json());
    if (found) {
      setLocation(found.latitude, found.longitude, 'manual', `Location set (${found.display}).`);
    } else {
      $('location-status').textContent = "Couldn't find that address — try adding the city and state.";
    }
  } catch {
    $('location-status').textContent = 'Address lookup failed — please try again.';
  }
});

// Submit
$('report-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  state.description = $('description').value;
  state.symptoms = $('symptoms').value;
  state.comments = $('comments').value;
  const body = buildSubmission(state);
  body.website = $('website').value; // if a bot filled the honeypot, send it along
  $('submit').disabled = true;
  $('form-error').hidden = true;
  try {
    const res = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const json = await res.json();
    if (json.ok) {
      $('report-form').hidden = true;
      $('thanks').hidden = false;
    } else {
      $('form-error').textContent = (json.errors || ['Something went wrong — please try again.']).join(' ');
      $('form-error').hidden = false;
      $('submit').disabled = false;
    }
  } catch {
    $('form-error').textContent = 'Could not reach the server — please try again.';
    $('form-error').hidden = false;
    $('submit').disabled = false;
  }
});

$('report-again').addEventListener('click', () => window.location.reload());
```

- [ ] **Step 6: Run the whole suite**

Run: `npx vitest run`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add smell-report-form/public smell-report-form/test/form-logic.test.js
git commit -m "feat: add mobile-first report form with GPS confirmation and manual address fallback"
```

---

### Task 8: Local end-to-end run + README

**Files:**
- Create: `smell-report-form/README.md`
- Modify: none (verification task)

**Interfaces:**
- Consumes: everything above, run under `wrangler pages dev` with a local D1.

- [ ] **Step 1: Boot the local stack**

```bash
cd smell-report-form
cp .dev.vars.example .dev.vars
npx wrangler d1 execute smell_reports --local --file=schema.sql
npx wrangler pages dev &
```

Wait for "Ready on http://localhost:8788" (port may differ — use what wrangler prints).

- [ ] **Step 2: Verify the API end-to-end with curl**

```bash
curl -s -X POST http://localhost:8788/api/report -H 'Content-Type: application/json' -d '{
  "smell_value": 4, "latitude": 37.033, "longitude": -88.35,
  "location_method": "gps", "smell_description": "e2e test", "website": ""
}'
```

Expected: `{"ok":true,"id":1}`.

```bash
curl -s -X POST http://localhost:8788/api/report -H 'Content-Type: application/json' \
  -d '{"smell_value": 9, "latitude": 37.033, "longitude": -88.35, "location_method": "gps"}'
```

Expected: HTTP 400 with a `smell_value` error.

```bash
curl -s http://localhost:8788/api/export -H 'Authorization: Bearer pick-a-long-random-string'
```

Expected: CSV with the header row and the "e2e test" report. (Token value comes from `.dev.vars`.)

```bash
curl -s -X POST http://localhost:8788/api/backfill -H 'Authorization: Bearer pick-a-long-random-string'
```

Expected: HTTP 409 `forwarding is not enabled` — proves the guardrail holds by default.

- [ ] **Step 3: Verify the form in a browser**

Open the printed localhost URL. Check: five rating buttons with the Smell MyCity labels render; Submit stays disabled until a rating AND location are set; "Use my location" prompts for permission; declining shows the manual address box; submitting shows the thank-you screen. Then stop the dev server.

- [ ] **Step 4: Write the README**

`smell-report-form/README.md`:

```markdown
# Calvert City Smell Report Form

A mobile-first web form for reporting odors in Calvert City, KY — built as the
landing page for our El Toro ad campaign so residents can file a report in
~30 seconds without downloading an app. Reports are stored in our own
Cloudflare D1 database and (once CREATE Lab issues us a `client_token`)
forwarded to [Smell MyCity](https://smellmycity.org)'s
`POST /api/v2/smell_reports` so they appear on their public map.

## How it works

- `public/` — static form. GPS via the browser permission prompt (with an
  "Is this right?" confirmation), manual address fallback, Smell MyCity's
  exact field set and rating wording.
- `functions/api/report.js` — validates (rating 1–5, coordinates inside the
  Calvert City region), rate-limits (5/hour/IP), rejects honeypot bots,
  stores to D1, and forwards to Smell MyCity when enabled.
- `functions/api/backfill.js` — forwards stored reports with
  `custom_time: true` + original `observed_at`, so pre-token reports land on
  their map at the true date and time.
- `functions/api/export.js` — token-protected CSV of everything (exact
  coordinates included — private use only).
- The local database is the source of truth. A failed forward never loses a
  report; backfill retries it.

## Local development

    npm install
    cp .dev.vars.example .dev.vars
    npx wrangler d1 execute smell_reports --local --file=schema.sql
    npm run dev

Tests: `npm test`

## Deploying (one-time setup)

1. `npx wrangler login`
2. `npx wrangler d1 create smell_reports` — paste the printed `database_id`
   into `wrangler.toml`.
3. `npx wrangler pages project create calvert-smell-report`
4. Apply the schema remotely:
   `npx wrangler d1 execute smell_reports --remote --file=schema.sql`
5. In the Cloudflare dashboard (Pages project → Settings → Variables and
   Secrets) set: `SMC_API_BASE`, `FORWARDING_ENABLED=false`,
   and secrets `SMC_CLIENT_TOKEN` (blank until CREATE Lab issues it),
   `EXPORT_TOKEN`, `RATE_SALT` (long random strings).
6. Deploy: `npx wrangler pages deploy`
7. Point the El Toro ad click-through URL at the deployed page.

## When the CREATE Lab token arrives

1. Confirm the production API base URL with CREATE Lab; update `SMC_API_BASE`.
2. Set the `SMC_CLIENT_TOKEN` secret, set `FORWARDING_ENABLED=true`, redeploy.
3. Forward the backlog with original timestamps:
   `curl -X POST https://<your-domain>/api/backfill -H 'Authorization: Bearer <EXPORT_TOKEN>'`
   Repeat until `remaining` is 0.

## Pulling data for analysis

    curl https://<your-domain>/api/export -H 'Authorization: Bearer <EXPORT_TOKEN>' > reports.csv

## Notes

- We never impersonate the Smell MyCity app's token; ours comes from CREATE
  Lab directly.
- Smell MyCity's server perturbs published locations by ~0.1 mile; our form
  sends precise coordinates exactly like their app does.
- Geocoding uses Nominatim (OpenStreetMap) from the visitor's browser at
  form-filling volume, per their usage policy.
```

- [ ] **Step 5: Commit**

```bash
git add smell-report-form/README.md
git commit -m "docs: add README with local dev, deploy, token-arrival, and export instructions"
```

---

### Task 9: CREATE Lab outreach email draft

**Files:**
- Create: `smell-report-form/docs/create-lab-email.md`

**Interfaces:**
- Consumes: nothing (writing task). The draft must reference the real endpoints/params built above.

- [ ] **Step 1: Write the draft**

`smell-report-form/docs/create-lab-email.md`:

```markdown
# Draft: client_token request to CMU CREATE Lab

*(Send via mentor's existing CREATE Lab contacts. Fill in the bracketed bits.)*

Subject: Client token request — web report form for Calvert City, KY

Hi [name],

I'm [your name], a student researcher working with [mentor's name] on an
air-quality project in Calvert City, Kentucky, where residents regularly
report industrial odor problems. We've been running geofenced ads encouraging
residents to file Smell MyCity reports, and we're getting good click-through —
but almost no completed reports, because the landing page asks people to
install the app and most drop off at that step.

We've built a lightweight mobile web form that mirrors the app's exact fields
(smell rating 1–5 with your wording, smell description, symptoms, comments,
and precise GPS or address-confirmed location with the user's consent). We'd
love to submit these reports through your documented
`POST /api/v2/smell_reports` endpoint so they appear alongside app reports —
and for that we're asking you to issue us a `client_token` for this form.

A few things we've already handled, so you know we'll be good citizens of
your dataset:

- Reports queue in our own database, and until a token exists nothing is sent
  to your servers. Forwarding is off by default.
- Queued reports would be backfilled with `custom_time: true` and their
  original `observed_at` timestamps, so nothing lands at a false time.
- We send a persistent anonymous `user_hash` per device, like the app does.
- The form has bot protection (honeypot + per-IP rate limiting) and
  server-side validation that rejects reports outside the Calvert City region.
- We understand published locations are perturbed on your side; our privacy
  note tells users exactly that.

Could you let us know the production API base URL we should use, and anything
else you'd want from us (a demo link, the source code — it's a small open
repo we're happy to share)?

Thank you — and thanks for building Smell MyCity in the first place; it's
been the backbone of our community's reporting.

[your name]
[school / program]
[phone / email]
```

- [ ] **Step 2: Commit**

```bash
git add smell-report-form/docs/create-lab-email.md
git commit -m "docs: draft CREATE Lab client_token request email"
```

---

## Verification checklist (end of plan)

- `npx vitest run` from `smell-report-form/` — every test green.
- Task 8's curl checks pass locally, including the 409 guardrail on backfill.
- `git log --oneline` shows one commit per task minimum.
- No secrets anywhere in the repo (`git grep -i "client_token ="` finds only code/docs references, no values; `.dev.vars` is gitignored).
