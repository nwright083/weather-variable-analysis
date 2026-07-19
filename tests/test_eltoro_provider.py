"""
test_eltoro_provider.py — the El Toro AdProvider adapter. It maps a census tract to
a PRE-APPROVED order line (from the mapping file) and toggles that order line on/off.
It must NEVER create order lines, and must REFUSE any tract / order line not in the
mapping (defense in depth against spending on the wrong thing).

Run:  python -m pytest tests/test_eltoro_provider.py -q
"""

import os
import sys
import json

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ad_providers.eltoro import ElToroAdProvider


class FakeClient:
    """Records the order-line actions the provider asks for."""

    def __init__(self, order_line=None):
        self.calls = []
        self._order_line = order_line or {"id": "ol-1", "status": "ACTIVE"}

    def request_review(self, order_line_id):
        self.calls.append(("request_review", order_line_id))
        return {"status": "ok"}

    def cancel_deployment(self, order_line_id):
        self.calls.append(("cancel_deployment", order_line_id))
        return {"status": "ok"}

    def get_order_line(self, order_line_id):
        self.calls.append(("get_order_line", order_line_id))
        return self._order_line


MAPPING = {
    "org_id": "org-1",
    "campaign_id": "camp-1",
    "order_lines": {
        "21157950101": "ol-100",
        "21157950102": "ol-200",
    },
}


def _provider(client=None, mapping=None):
    return ElToroAdProvider(client=client or FakeClient(), mapping=mapping or MAPPING)


class TestIdentity:
    def test_name(self):
        assert _provider().name == "eltoro"


class TestActivate:
    def test_known_tract_deploys_mapped_order_line(self):
        client = FakeClient()
        p = _provider(client=client)
        result = p.activate_campaign(
            tract_id="21157950101", tract_name="Tract A",
            start_date="2026-07-25", end_date="2026-07-26", ori_score=0.45,
        )
        assert result["status"] == "ok"
        # The returned campaign_id is the order-line id, so ad_trigger state tracks it.
        assert result["campaign_id"] == "ol-100"
        assert ("request_review", "ol-100") in client.calls

    def test_unknown_tract_is_refused_and_calls_no_client(self):
        client = FakeClient()
        p = _provider(client=client)
        with pytest.raises(ValueError):
            p.activate_campaign(
                tract_id="99999999999", tract_name="Not mapped",
                start_date="2026-07-25", end_date="2026-07-26", ori_score=0.9,
            )
        assert client.calls == []  # nothing touched — no spend risk

    def test_empty_mapping_refuses_everything(self):
        client = FakeClient()
        p = ElToroAdProvider(client=client, mapping={"order_lines": {}})
        with pytest.raises(ValueError):
            p.activate_campaign(
                tract_id="21157950101", tract_name="Tract A",
                start_date="2026-07-25", end_date="2026-07-26", ori_score=0.45,
            )
        assert client.calls == []


class TestDeactivate:
    def test_known_order_line_is_cancelled(self):
        client = FakeClient()
        p = _provider(client=client)
        result = p.deactivate_campaign("ol-100")
        assert result["status"] == "ok"
        assert ("cancel_deployment", "ol-100") in client.calls

    def test_unknown_order_line_is_refused(self):
        client = FakeClient()
        p = _provider(client=client)
        with pytest.raises(ValueError):
            p.deactivate_campaign("ol-999-not-ours")
        assert client.calls == []


class TestStatus:
    def test_get_campaign_status_reads_order_line(self):
        client = FakeClient(order_line={"id": "ol-100", "status": "ACTIVE"})
        p = _provider(client=client)
        status = p.get_campaign_status("ol-100")
        assert status["campaign_id"] == "ol-100"
        assert ("get_order_line", "ol-100") in client.calls


class TestMappingFile:
    def test_loads_mapping_from_file_path(self, tmp_path):
        path = tmp_path / "eltoro_order_lines.json"
        path.write_text(json.dumps(MAPPING))
        client = FakeClient()
        p = ElToroAdProvider(client=client, mapping_path=str(path))
        result = p.activate_campaign(
            tract_id="21157950102", tract_name="Tract B",
            start_date="2026-07-25", end_date="2026-07-26", ori_score=0.5,
        )
        assert result["campaign_id"] == "ol-200"
        assert ("request_review", "ol-200") in client.calls

    def test_missing_mapping_file_yields_empty_and_refuses(self, tmp_path):
        client = FakeClient()
        p = ElToroAdProvider(client=client, mapping_path=str(tmp_path / "nope.json"))
        with pytest.raises(ValueError):
            p.activate_campaign(
                tract_id="21157950101", tract_name="Tract A",
                start_date="2026-07-25", end_date="2026-07-26", ori_score=0.45,
            )
        assert client.calls == []
