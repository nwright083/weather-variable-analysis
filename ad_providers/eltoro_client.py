"""
ad_providers.eltoro_client — Thin REST client for the El Toro Platform API.

Responsibilities (and nothing more — no business logic lives here):
  * OAuth2 client-credentials token management: fetch, cache, and auto-refresh
    the bearer token (El Toro tokens expire in ~5 minutes).
  * The handful of order-line endpoints the ad trigger needs.

Auth + endpoints per https://docs.api.eltoro.com/ (2026-07-19):
  * Token endpoint (prod): https://auth.api.eltoro.com/auth/realms/eltoro/protocol/openid-connect/token
  * Base API URL (prod):   https://hagrid.api.eltoro.com   (docs warn this host will change)
  * Grant: POST application/x-www-form-urlencoded, grant_type=client_credentials,
           client_id, client_secret -> { access_token, token_type, expires_in }

The HTTP session and clock are injectable so the client is fully unit-testable
without touching the network.
"""

from __future__ import annotations

import time
import urllib.parse


# ── Endpoint constants (single source of truth; update if El Toro changes hosts) ──
PROD_BASE_URL = "https://hagrid.api.eltoro.com"
DEV_BASE_URL = "https://hagrid.api.dev.eltoro.com"
PROD_TOKEN_URL = "https://auth.api.eltoro.com/auth/realms/eltoro/protocol/openid-connect/token"
DEV_TOKEN_URL = "https://auth.api.dev.eltoro.com/auth/realms/eltoro/protocol/openid-connect/token"

# Refresh the token this many seconds before it actually expires, so an in-flight
# request never races the expiry.
_TOKEN_REFRESH_MARGIN_S = 30

# Network timeout (seconds) for every HTTP call — never hang a cron job forever.
_HTTP_TIMEOUT_S = 30


class ElToroApiError(RuntimeError):
    """Raised when El Toro returns a non-2xx response (auth or API)."""

    def __init__(self, message, *, status_code=None, url=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body = body


class ElToroClient:
    """Minimal El Toro Platform API client with client-credentials auth."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str = PROD_BASE_URL,
        token_url: str = PROD_TOKEN_URL,
        session=None,
        clock=time.monotonic,
    ):
        if not client_id or not client_secret:
            raise ValueError(
                "El Toro client_id and client_secret are required. Set ELTORO_CLIENT_ID "
                "and ELTORO_CLIENT_SECRET (El Toro's team provisions these during onboarding)."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._clock = clock

        if session is None:
            import requests  # imported lazily so tests need no network stack
            session = requests.Session()
        self._session = session

        self._token: str | None = None
        self._token_expiry: float = 0.0  # clock() value at/after which the token is stale

    # ── Token management ──────────────────────────────────────────────────────
    def _fetch_token(self) -> None:
        resp = self._session.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_HTTP_TIMEOUT_S,
        )
        if not (200 <= resp.status_code < 300):
            raise ElToroApiError(
                f"Token request failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                url=self._token_url,
                body=getattr(resp, "text", ""),
            )
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise ElToroApiError(
                "Token response contained no access_token",
                status_code=resp.status_code,
                url=self._token_url,
                body=payload,
            )
        expires_in = float(payload.get("expires_in", 300))
        self._token = token
        self._token_expiry = self._clock() + expires_in - _TOKEN_REFRESH_MARGIN_S

    def _valid_token(self) -> str:
        if self._token is None or self._clock() >= self._token_expiry:
            self._fetch_token()
        return self._token  # type: ignore[return-value]

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._valid_token()}"}

    # ── HTTP helpers ──────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self._base_url}{path}"
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}
        if method == "GET":
            resp = self._session.get(url, headers=headers, timeout=_HTTP_TIMEOUT_S, **kwargs)
        elif method == "POST":
            resp = self._session.post(url, headers=headers, timeout=_HTTP_TIMEOUT_S, **kwargs)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        if not (200 <= resp.status_code < 300):
            raise ElToroApiError(
                f"{method} {url} failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                url=url,
                body=getattr(resp, "text", ""),
            )
        return resp.json()

    # ── Order-line endpoints ──────────────────────────────────────────────────
    def get_order_line(self, order_line_id: str) -> dict:
        """GET a single order line by id."""
        return self._request("GET", f"/v1/order-lines/{urllib.parse.quote(order_line_id)}")

    def list_order_lines(self, **params) -> dict:
        """GET the order-lines collection (optional query params, e.g. campaign filters)."""
        kwargs = {"params": params} if params else {}
        return self._request("GET", "/v1/order-lines", **kwargs)

    def request_review(self, order_line_id: str) -> dict:
        """POST :requestReview — submit an order line for review/deployment.

        NOTE: this is the action that leads to real ad spend. Callers gate it behind
        the dry-run / --live / ELTORO_ENABLED guardrails in ad_trigger.
        """
        return self._request(
            "POST", f"/v1/order-lines/{urllib.parse.quote(order_line_id)}:requestReview"
        )

    def cancel_deployment(self, order_line_id: str) -> dict:
        """POST :cancelDeployment — stop a deploying/serving order line."""
        return self._request(
            "POST", f"/v1/order-lines/{urllib.parse.quote(order_line_id)}:cancelDeployment"
        )

    def get_balance(self, org_id: str) -> dict:
        """GET an org's balance — used only as an optional pre-flight sanity check.

        The exact path is not yet confirmed against a live account; keep this call
        non-fatal in callers until verified with El Toro.
        """
        return self._request("GET", f"/v1/orgs/{urllib.parse.quote(org_id)}/balance")
