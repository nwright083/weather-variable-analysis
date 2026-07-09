"""
ad_providers.mock — Mock ad provider for testing the ad trigger pipeline.

Logs all activate/deactivate calls to stdout and to the configured log file.
Returns fake campaign IDs. Does not contact any real ad service.

Safe to use in CI, local testing, and development.
"""

import uuid
import datetime
from ad_providers.base import AdProvider


class MockAdProvider(AdProvider):
    """Mock ad provider that logs actions without contacting any real service."""

    def __init__(self):
        # In-memory tracking of "active" mock campaigns
        self._campaigns = {}

    @property
    def name(self) -> str:
        return "mock"

    def activate_campaign(
        self,
        tract_id: str,
        tract_name: str,
        start_date: str,
        end_date: str,
        ori_score: float,
        metadata: dict | None = None,
    ) -> dict:
        campaign_id = f"mock-{uuid.uuid4().hex[:8]}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        campaign = {
            "campaign_id": campaign_id,
            "tract_id": tract_id,
            "tract_name": tract_name,
            "start_date": start_date,
            "end_date": end_date,
            "ori_score": ori_score,
            "state": "active",
            "created_utc": now,
            "metadata": metadata or {},
        }
        self._campaigns[campaign_id] = campaign

        print(
            f"[MOCK AD] ACTIVATE  tract={tract_id} ({tract_name})  "
            f"ORI={ori_score:.1%}  dates={start_date}→{end_date}  "
            f"campaign_id={campaign_id}"
        )
        return {"status": "ok", "campaign_id": campaign_id}

    def deactivate_campaign(self, campaign_id: str) -> dict:
        if campaign_id in self._campaigns:
            self._campaigns[campaign_id]["state"] = "deactivated"
            tract_id = self._campaigns[campaign_id]["tract_id"]
            print(f"[MOCK AD] DEACTIVATE  campaign={campaign_id}  tract={tract_id}")
            return {"status": "ok", "campaign_id": campaign_id}
        else:
            print(f"[MOCK AD] DEACTIVATE  campaign={campaign_id}  (not found, ignoring)")
            return {"status": "ok", "campaign_id": campaign_id, "note": "not found"}

    def get_campaign_status(self, campaign_id: str) -> dict:
        if campaign_id in self._campaigns:
            state = self._campaigns[campaign_id]["state"]
            return {"status": "ok", "campaign_id": campaign_id, "state": state}
        return {"status": "ok", "campaign_id": campaign_id, "state": "unknown"}

    def list_active_campaigns(self) -> list[dict]:
        return [
            c for c in self._campaigns.values()
            if c["state"] == "active"
        ]
