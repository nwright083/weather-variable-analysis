"""
ad_providers.eltoro — El Toro ad provider adapter (pre-provisioned, toggle-only).

El Toro (eltoro.com) is an IP-Targeting / GeoFraming ad-tech company. In El Toro's
model the money-spending unit is an **Order Line** (Org -> Campaign -> Order Lines;
each order line carries a target/geofence, creative, CPM, budget and flight dates).

This adapter deliberately does the SMALLEST possible thing, for money safety:

  * A human, with the El Toro rep, pre-creates the campaign, geofenced targets,
    creatives and one order line per target area IN THE PORTAL, with fixed budgets.
  * Those order-line ids are recorded in a mapping file (eltoro_order_lines.json).
  * This adapter ONLY turns those pre-approved order lines on/off, keyed by tract.

It NEVER creates order lines, NEVER sets or changes budgets, and REFUSES any tract
or order line that is not in the mapping. Worst case: it toggles order lines whose
spend was already capped by a human.

The single on/off primitive is isolated in `_set_serving()` — see the CONFIRM-WITH-REP
note there; whichever mechanism El Toro uses to re-enable an order line, only that one
method changes.
"""

from __future__ import annotations

import os
import json

from ad_providers.base import AdProvider


class ElToroAdProvider(AdProvider):
    """Toggles pre-approved El Toro order lines on/off, keyed by census tract."""

    def __init__(self, client=None, mapping: dict | None = None, mapping_path: str | None = None):
        """
        Args:
            client:       An ElToroClient (or compatible). If None, one is built lazily
                          from environment credentials the first time it is needed, so
                          constructing the provider never requires secrets (safe for
                          dry-run / import).
            mapping:      Pre-loaded mapping dict {org_id, campaign_id, order_lines:{tract:ol}}.
            mapping_path: Path to a mapping JSON file. Ignored if `mapping` is given.
                          Defaults to ad_config.ELTORO_MAPPING_FILE. A missing file yields
                          an empty mapping, which refuses every tract (fail safe).
        """
        self._client = client
        if mapping is not None:
            self._mapping = mapping
        else:
            self._mapping = self._load_mapping(mapping_path)

        order_lines = self._mapping.get("order_lines", {}) or {}
        self._tract_to_ol: dict[str, str] = dict(order_lines)
        self._known_ol_ids: set[str] = set(order_lines.values())

    # ── Setup helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _load_mapping(mapping_path: str | None) -> dict:
        if mapping_path is None:
            try:
                import ad_config
                mapping_path = getattr(ad_config, "ELTORO_MAPPING_FILE", None)
            except Exception:
                mapping_path = None
        if mapping_path and os.path.exists(mapping_path):
            with open(mapping_path) as f:
                return json.load(f)
        return {"order_lines": {}}

    def _get_client(self):
        """Return the injected client, or build a real one from env credentials."""
        if self._client is None:
            from ad_providers.eltoro_client import ElToroClient, PROD_BASE_URL, PROD_TOKEN_URL, \
                DEV_BASE_URL, DEV_TOKEN_URL
            try:
                import ad_config
                env = getattr(ad_config, "ELTORO_ENV", "prod")
                base_url = getattr(ad_config, "ELTORO_BASE_URL", None)
            except Exception:
                env, base_url = "prod", None
            base = base_url or (DEV_BASE_URL if env == "dev" else PROD_BASE_URL)
            token = DEV_TOKEN_URL if env == "dev" else PROD_TOKEN_URL
            self._client = ElToroClient(
                client_id=os.environ.get("ELTORO_CLIENT_ID", ""),
                client_secret=os.environ.get("ELTORO_CLIENT_SECRET", ""),
                base_url=base,
                token_url=token,
            )
        return self._client

    # ── The single on/off primitive (CONFIRM WITH REP) ────────────────────────
    def _set_serving(self, order_line_id: str, serving: bool) -> dict:
        """Turn a pre-approved order line ON (serving=True) or OFF (serving=False).

        DEFAULT strategy, based on El Toro's documented lifecycle:
            ON  -> requestReview  (submits the order line for deployment/serving)
            OFF -> cancelDeployment

        CONFIRM WITH EL TORO REP: how an order line is re-enabled after being stopped
        (fresh requestReview each time vs. pause/play schedules). If it turns out to be
        pause/play, change ONLY this method to call the corresponding client endpoints.
        Nothing else in the codebase depends on the choice.
        """
        client = self._get_client()
        if serving:
            return client.request_review(order_line_id)
        return client.cancel_deployment(order_line_id)

    # ── AdProvider interface ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "eltoro"

    def activate_campaign(
        self,
        tract_id: str,
        tract_name: str,
        start_date: str,
        end_date: str,
        ori_score: float,
        metadata: dict | None = None,
    ) -> dict:
        order_line_id = self._tract_to_ol.get(tract_id)
        if not order_line_id:
            raise ValueError(
                f"Refusing to activate: tract {tract_id} ({tract_name}) has no pre-approved "
                f"order line in the El Toro mapping. Add it to the mapping file first. "
                f"(The daily automation never creates order lines.)"
            )
        self._set_serving(order_line_id, True)
        # campaign_id == order_line_id so ad_trigger's state machine tracks the real thing.
        return {"status": "ok", "campaign_id": order_line_id, "order_line_id": order_line_id}

    def deactivate_campaign(self, campaign_id: str) -> dict:
        # campaign_id is the order-line id we returned from activate_campaign.
        if campaign_id not in self._known_ol_ids:
            raise ValueError(
                f"Refusing to deactivate: order line {campaign_id!r} is not in the El Toro "
                f"mapping. This adapter only touches pre-approved order lines."
            )
        self._set_serving(campaign_id, False)
        return {"status": "ok", "campaign_id": campaign_id}

    def get_campaign_status(self, campaign_id: str) -> dict:
        ol = self._get_client().get_order_line(campaign_id)
        return {
            "status": "ok",
            "campaign_id": campaign_id,
            "state": ol.get("status") or ol.get("state") or "unknown",
            "raw": ol,
        }

    def list_active_campaigns(self) -> list[dict]:
        """List order lines known to this mapping and their current state."""
        client = self._get_client()
        out = []
        for tract_id, ol_id in self._tract_to_ol.items():
            try:
                ol = client.get_order_line(ol_id)
                out.append({
                    "campaign_id": ol_id,
                    "tract_id": tract_id,
                    "state": ol.get("status") or ol.get("state") or "unknown",
                })
            except Exception:
                out.append({"campaign_id": ol_id, "tract_id": tract_id, "state": "unknown"})
        return out
