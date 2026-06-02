"""Tests for is_trading_day / next_trading_day / compute_last_trading_day."""
import datetime as dt

import pytest

import indian_market_calendar as imc
from indian_market_calendar import (
    compute_last_trading_day,
    is_trading_day,
    next_trading_day,
)

HOLIDAYS = [
    dt.date(2025, 1, 26),
    dt.date(2025, 3, 14),   # Holi (Friday)
    dt.date(2025, 8, 15),   # Independence Day (Friday)
    dt.date(2025, 10, 2),   # Gandhi Jayanti (Thursday)
]


@pytest.fixture(autouse=True)
def _mock_holidays(monkeypatch):
    monkeypatch.setattr(imc, "load_holidays", lambda: list(HOLIDAYS))


class TestIsTradingDay:
    def test_weekday_non_holiday(self):
        assert is_trading_day(dt.date(2025, 3, 12)) is True  # Wednesday

    def test_saturday(self):
        assert is_trading_day(dt.date(2025, 3, 15)) is False

    def test_sunday(self):
        assert is_trading_day(dt.date(2025, 3, 16)) is False

    def test_holiday(self):
        assert is_trading_day(dt.date(2025, 3, 14)) is False


class TestNextTradingDay:
    def test_simple_next(self):
        assert next_trading_day(dt.date(2025, 3, 12)) == dt.date(2025, 3, 13)

    def test_skips_weekend(self):
        # Friday Mar 21 → Monday Mar 24
        assert next_trading_day(dt.date(2025, 3, 21)) == dt.date(2025, 3, 24)

    def test_skips_holiday_and_weekend(self):
        # Thursday Mar 13 → Fri Mar 14 (Holi) → skip Sat/Sun → Mon Mar 17
        assert next_trading_day(dt.date(2025, 3, 13)) == dt.date(2025, 3, 17)


class TestComputeLastTradingDay:
    def test_weekday_after_close(self, monkeypatch):
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 12))
        monkeypatch.setattr(imc, "is_after_market_close", lambda: True)
        assert compute_last_trading_day() == dt.date(2025, 3, 12)

    def test_weekday_before_close(self, monkeypatch):
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 12))
        monkeypatch.setattr(imc, "is_after_market_close", lambda: False)
        assert compute_last_trading_day() == dt.date(2025, 3, 11)

    def test_saturday_after_close(self, monkeypatch):
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 15))
        monkeypatch.setattr(imc, "is_after_market_close", lambda: True)
        # Sat → Fri Mar 14 (Holi) → Thu Mar 13
        assert compute_last_trading_day() == dt.date(2025, 3, 13)

    def test_holiday_after_close(self, monkeypatch):
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 8, 15))
        monkeypatch.setattr(imc, "is_after_market_close", lambda: True)
        assert compute_last_trading_day() == dt.date(2025, 8, 14)
