"""Tests for is_market_open boundary cases (<= close boundary)."""
import datetime as dt

import pytest

import indian_market_calendar as imc
from indian_market_calendar import IST, Market, is_market_open


@pytest.fixture(autouse=True)
def _no_holidays(monkeypatch):
    monkeypatch.setattr(imc, "load_holidays", list)


def _t(y, m, d, h, minute=0, second=0):
    return dt.datetime(y, m, d, h, minute, second, tzinfo=IST)


# 2026-04-24 is a Friday (trading day); 2026-04-25 a Saturday.
class TestBoundaries:
    def test_at_open(self):
        assert is_market_open(_t(2026, 4, 24, 9, 15)) is True

    def test_before_open(self):
        assert is_market_open(_t(2026, 4, 24, 9, 14, 59)) is False

    def test_midday(self):
        assert is_market_open(_t(2026, 4, 24, 12, 0)) is True

    def test_exactly_at_close_is_open(self):
        # 15:30:00 inclusive — finance_website boundary, no 1-second limbo
        assert is_market_open(_t(2026, 4, 24, 15, 30, 0)) is True

    def test_one_second_after_close_is_closed(self):
        assert is_market_open(_t(2026, 4, 24, 15, 30, 1)) is False

    def test_weekend(self):
        assert is_market_open(_t(2026, 4, 25, 12, 0)) is False


class TestHoliday:
    def test_holiday_closed(self, monkeypatch):
        monkeypatch.setattr(imc, "load_holidays", lambda: [dt.date(2026, 4, 24)])
        assert is_market_open(_t(2026, 4, 24, 12, 0)) is False


class TestDefaultNow:
    def test_uses_now_when_none(self, monkeypatch):
        monkeypatch.setattr(imc, "now", lambda: _t(2026, 4, 24, 12, 0))
        assert is_market_open() is True


class TestNyse:
    def test_nyse_not_implemented(self):
        with pytest.raises(NotImplementedError):
            is_market_open(market=Market.NYSE)
