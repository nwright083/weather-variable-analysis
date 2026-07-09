"""
ad_providers.base — Abstract interface for ad provider adapters.

Any ad provider integration (El Toro, mock, future providers) must subclass
AdProvider and implement all abstract methods. This ensures the ad_trigger
engine can swap providers without changing its own logic.
"""

from abc import ABC, abstractmethod


class AdProvider(ABC):
    """Abstract base class for ad provider integrations.

    Each method receives structured data about the campaign and returns a dict
    with at minimum a "status" key ("ok" or "error") and a "campaign_id" key.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g., 'mock', 'eltoro')."""

    @abstractmethod
    def activate_campaign(
        self,
        tract_id: str,
        tract_name: str,
        start_date: str,
        end_date: str,
        ori_score: float,
        metadata: dict | None = None,
    ) -> dict:
        """Activate (or create) an ad campaign for a census tract.

        Args:
            tract_id:   GEOID string (e.g., "21157950101").
            tract_name: Human-readable tract name.
            start_date: ISO date string for campaign start (e.g., "2026-07-09").
            end_date:   ISO date string for campaign end (inclusive).
            ori_score:  The ORI probability (0–1) that triggered this campaign.
            metadata:   Optional dict with extra context (model mode, threshold, etc.).

        Returns:
            Dict with at least:
                {"status": "ok", "campaign_id": "...", ...}
            or on failure:
                {"status": "error", "message": "...", ...}
        """

    @abstractmethod
    def deactivate_campaign(self, campaign_id: str) -> dict:
        """Deactivate (pause/stop) an existing campaign.

        Args:
            campaign_id: The ID returned by activate_campaign.

        Returns:
            {"status": "ok", "campaign_id": "..."} or {"status": "error", ...}
        """

    @abstractmethod
    def get_campaign_status(self, campaign_id: str) -> dict:
        """Check the current status of a campaign.

        Args:
            campaign_id: The ID returned by activate_campaign.

        Returns:
            {"status": "ok", "campaign_id": "...", "state": "active"|"paused"|"expired"|"unknown"}
        """

    @abstractmethod
    def list_active_campaigns(self) -> list[dict]:
        """List all currently active campaigns managed by this provider.

        Returns:
            List of dicts, each with at least {"campaign_id": "...", "tract_id": "...", "state": "..."}.
        """
