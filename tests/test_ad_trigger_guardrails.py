"""
test_ad_trigger_guardrails.py — the money-safety gates in ad_trigger:

  * effective_dry_run(): the two-key live gate. A run spends real money ONLY when
    the operator passes --live AND (for El Toro) the ELTORO_ENABLED switch is on.
  * coverage_dates(): weekday-aware look-ahead. Deploys happen on weekday business
    hours and run on later days, so a Friday run must cover Sat + Sun + Mon.

Run:  python -m pytest tests/test_ad_trigger_guardrails.py -q
"""

import os
import sys
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ad_trigger import effective_dry_run, coverage_dates, business_hours_status


class TestLiveGate:
    def test_not_live_is_always_dry(self):
        assert effective_dry_run(live=False, provider_name="mock", eltoro_enabled=True) is True
        assert effective_dry_run(live=False, provider_name="eltoro", eltoro_enabled=True) is True

    def test_live_mock_is_not_dry(self):
        # mock provider spends nothing, so --live is enough
        assert effective_dry_run(live=True, provider_name="mock", eltoro_enabled=False) is False

    def test_live_eltoro_requires_enabled_switch(self):
        # --live but the ELTORO_ENABLED kill-switch is off -> forced dry (no spend)
        assert effective_dry_run(live=True, provider_name="eltoro", eltoro_enabled=False) is True

    def test_live_eltoro_with_enabled_switch_spends(self):
        assert effective_dry_run(live=True, provider_name="eltoro", eltoro_enabled=True) is False

    def test_force_dry_run_overrides_everything(self):
        assert effective_dry_run(
            live=True, provider_name="eltoro", eltoro_enabled=True, force_dry_run=True
        ) is True


class TestCoverageDates:
    def test_weekday_covers_next_day_only(self):
        wed = datetime.date(2026, 7, 22)  # Wednesday
        assert wed.weekday() == 2
        assert coverage_dates(wed) == [datetime.date(2026, 7, 23)]

    def test_friday_covers_weekend_and_monday(self):
        fri = datetime.date(2026, 7, 24)  # Friday
        assert fri.weekday() == 4
        assert coverage_dates(fri) == [
            datetime.date(2026, 7, 25),  # Sat
            datetime.date(2026, 7, 26),  # Sun
            datetime.date(2026, 7, 27),  # Mon
        ]

    def test_thursday_covers_friday_only(self):
        thu = datetime.date(2026, 7, 23)  # Thursday
        assert coverage_dates(thu) == [datetime.date(2026, 7, 24)]


class TestBusinessHours:
    TZ = "America/New_York"
    KW = dict(tz_name=TZ, start_hour=9, end_hour=17, business_days=(0, 1, 2, 3, 4))

    def test_weekday_midday_is_within(self):
        # 2026-07-22 15:00 UTC = 11:00 ET on a Wednesday
        dt = datetime.datetime(2026, 7, 22, 15, 0, tzinfo=datetime.timezone.utc)
        within, local = business_hours_status(dt, **self.KW)
        assert within is True
        assert local.hour == 11

    def test_weekday_night_is_outside(self):
        # 2026-07-22 06:00 UTC = 02:00 ET (before 09:00)
        dt = datetime.datetime(2026, 7, 22, 6, 0, tzinfo=datetime.timezone.utc)
        within, _ = business_hours_status(dt, **self.KW)
        assert within is False

    def test_weekend_is_outside(self):
        # 2026-07-25 is a Saturday; 15:00 UTC = 11:00 ET but not a business day
        dt = datetime.datetime(2026, 7, 25, 15, 0, tzinfo=datetime.timezone.utc)
        within, _ = business_hours_status(dt, **self.KW)
        assert within is False
