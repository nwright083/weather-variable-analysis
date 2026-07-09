"""
ad_providers.eltoro — El Toro GeoFraming™ ad provider adapter.

El Toro (eltoro.com) is an advertising technology company based in Louisville, KY
that uses GeoFraming™ — a proprietary technology that captures mobile device IDs
at physical locations and matches them to household IP addresses for targeted
digital advertising.

STATUS: PLACEHOLDER — El Toro is a service-based platform and does not currently
offer a public REST API. This adapter will be implemented once their team provides
API access details or an alternative integration method (CSV upload, webhook, etc.).

Contact El Toro:
    Phone: (502) 353-0390
    Website: https://www.eltoro.com
    Relevant products: GeoFraming, IP Targeting, Location to Lead (L2L)

Integration notes to resolve with El Toro:
    1. Can campaigns be activated/deactivated programmatically?
    2. What format do they need for geofence boundaries (tract polygons)?
    3. What's the minimum lead time from activation to ad serving?
    4. Is there a minimum campaign duration?
    5. Do they support census tract GEOIDs, or do they need lat/lon polygons?
    6. Rate limits / authentication for any programmatic access?
"""

from ad_providers.base import AdProvider


class ElToroAdProvider(AdProvider):
    """El Toro GeoFraming ad provider — NOT YET IMPLEMENTED.

    This class exists as a placeholder so the framework is ready to integrate
    once El Toro provides API access or an alternative programmatic interface.
    """

    @property
    def name(self) -> str:
        return "eltoro"

    def activate_campaign(self, tract_id, tract_name, start_date, end_date, ori_score, metadata=None):
        raise NotImplementedError(
            "El Toro integration is not yet implemented. "
            "Contact their team at (502) 353-0390 or eltoro.com for API access details. "
            "Once you know their interface, implement this method to create/activate "
            "a GeoFraming campaign for the given census tract."
        )

    def deactivate_campaign(self, campaign_id):
        raise NotImplementedError(
            "El Toro integration is not yet implemented. "
            "See activate_campaign docstring for next steps."
        )

    def get_campaign_status(self, campaign_id):
        raise NotImplementedError(
            "El Toro integration is not yet implemented. "
            "See activate_campaign docstring for next steps."
        )

    def list_active_campaigns(self):
        raise NotImplementedError(
            "El Toro integration is not yet implemented. "
            "See activate_campaign docstring for next steps."
        )
