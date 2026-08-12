# Calvert City Smell Report Form — Design

**Date:** 2026-08-12
**Status:** Approved by user (this document is the written record for review)

## Problem

El Toro ads for the Calvert City odor campaign get a good click rate (~0.2), but clicks
produce almost no new smell reports. The click-through currently lands on the Smell MyCity
website, which asks people to download an app — and most ad-clickers drop off at that step.

## Goal

Replace the ad click-through destination with a web form that files a smell report in under
30 seconds with no app download, and get those reports into Smell MyCity's database so they
appear on their public map alongside app-submitted reports.

## Key feasibility findings

- Smell MyCity's backend is open source:
  [CMU-CREATE-Lab/smell-pittsburgh-rails](https://github.com/CMU-CREATE-Lab/smell-pittsburgh-rails).
- `POST /api/v2/smell_reports` accepts reports with latitude, longitude, `smell_value` (1–5),
  smell description, symptoms, and comments.
- Submission requires a `client_token` that "uniquely identifies an authorized Client."
  The token system exists so third-party clients can submit; obtaining one is an email to
  CREATE Lab (routed through the mentor's existing contacts), not a formal partnership.
- **We will not impersonate the mobile app's token.** Unauthorized submission would
  misattribute reports in a research dataset and violate their authorization system.
- Backfill is supported: `observed_at` (RFC 3339) is honored when `custom_time: true`,
  so reports stored while awaiting the token forward later with their original timestamps.
- Location privacy is handled server-side by Smell MyCity: their database stores
  "a perturbed lat/long position," so web-form reports get the same public-map fuzzing
  as app reports.

## Architecture

One GitHub repo (later pushed to the school's GitHub organization, like other project repos),
deployed on Cloudflare Pages free tier:

| Piece | Choice | Why |
|---|---|---|
| Frontend | Static HTML/JS form page | Mobile-first; ad clicks are mostly phones |
| Backend | Cloudflare Pages Functions, `POST /api/report` | Same repo, no servers, no cold-start sleep |
| Database | Cloudflare D1 (SQLite, free) | Source of truth for every report |
| Secrets | Cloudflare env settings: `SMC_CLIENT_TOKEN`, `FORWARDING_ENABLED` | Token never in the repo; forwarding off by default |

Rejected alternatives: Google Apps Script + existing Sheet (slow cold loads on ad clicks,
clunky form, fragile backfill); Render free tier (instances sleep ~15 min; a 30-second blank
page on an ad click loses the report).

## Form fields — exact mirror of Smell MyCity

Lossless forwarding; no extra research questions (shorter form → more completions):

1. Smell rating 1–5, using Smell MyCity's wording ("Just fine!" → "About as bad as it gets!")
2. Smell description (free text, e.g. "rotten eggs, chemical")
3. Symptoms (free text)
4. Optional comment
5. Location: browser geolocation permission prompt (same consent flow as the app),
   requested in high-accuracy mode — device GPS, never silent IP-based guessing.
   The form then shows the detected location back to the person (reverse-geocoded
   address) with an "Is this right?" confirmation; they can correct it by typing a
   street address. Manual address entry is also the fallback if permission is
   declined or GPS fails, so a declined prompt never loses a report.
6. Short privacy note: reports appear on Smell MyCity's public map at approximate
   (perturbed) locations

## Data flow

1. Submit → server-side validation → insert into D1 with exact timestamp (to the second)
   and `forwarded = 0`. D1 is the source of truth.
2. If `FORWARDING_ENABLED` and token present: immediately POST to
   `api/v2/smell_reports`; on success mark `forwarded = 1` and store the response.
3. Backfill (run once when the token arrives, and as retry for any failed forwards):
   posts each unforwarded report with `custom_time: true` and its original `observed_at`,
   so the backlog lands on their map at true dates/times.
4. A failed forward never loses a report — it stays local and is retried by backfill.

## Abuse protection

Ads attract bots, and polluting CREATE Lab's research dataset would burn the trust the
token request asks for:

- Honeypot form field
- Per-IP rate limiting
- Server-side validation: rating in 1–5, coordinates within the Calvert City region,
  field length limits

## Data access

Token-protected CSV export endpoint (exact coordinates included — private use only,
e.g. pulling into Sheets or the rain→odor analysis). Any future public-facing map of our
own must perturb locations the way Smell MyCity does.

## Error handling

- Smell MyCity unreachable / non-2xx → report saved locally, marked unforwarded, retried later
- Geolocation denied → manual address entry
- Validation failure → inline form error, nothing stored
- Duplicate rapid submissions from one IP → rate-limited with a friendly message

## Testing

- Unit tests for handler logic: validation, honeypot/rate-limit paths, forwarding,
  backfill timestamp formatting — against a mocked Smell MyCity endpoint
- Local end-to-end run with `wrangler` (form → function → local D1) before deploy
- Forwarding stays disabled until the token exists and a dry run against their docs
  is reviewed

## Also delivered with the build

Draft email to CREATE Lab (sent via mentor's contacts): who we are, the Calvert City
campaign, why the app-download step loses reporters, and the request for a `client_token`
for this form, noting correct use of `custom_time`/`observed_at` for backfill.

## Out of scope (YAGNI)

- Our own public map or dashboard
- User accounts of any kind
- Extra research questions on the form
- Integration with the El Toro ad-decision pipeline (the form is just the ad's landing page)
