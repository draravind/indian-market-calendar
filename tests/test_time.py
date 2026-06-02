"""Tests for the IST time helpers."""
import datetime as dt
from unittest.mock import patch

import indian_market_calendar as imc
from indian_market_calendar import IST, is_after_market_close, now, today


class TestNow:
    def test_returns_aware_datetime(self):
        result = now()
        assert isinstance(result, dt.datetime)
        assert result.tzinfo is not None

    def test_timezone_is_ist(self):
        assert str(now().tzinfo) == "Asia/Kolkata"


class TestToday:
    def test_returns_date(self):
        result = today()
        assert isinstance(result, dt.date)
        assert not isinstance(result, dt.datetime)

    def test_matches_now_date(self):
        assert today() == now().date()


class TestIsAfterMarketClose:
    def test_before_close(self):
        fake = dt.datetime(2025, 3, 12, 10, 0, tzinfo=IST)
        with patch.object(imc, "now", return_value=fake):
            assert is_after_market_close() is False

    def test_after_close(self):
        fake = dt.datetime(2025, 3, 12, 16, 0, tzinfo=IST)
        with patch.object(imc, "now", return_value=fake):
            assert is_after_market_close() is True

    def test_exactly_at_close(self):
        fake = dt.datetime(2025, 3, 12, 15, 30, tzinfo=IST)
        with patch.object(imc, "now", return_value=fake):
            assert is_after_market_close() is False

    def test_one_minute_after_close(self):
        fake = dt.datetime(2025, 3, 12, 15, 31, tzinfo=IST)
        with patch.object(imc, "now", return_value=fake):
            assert is_after_market_close() is True
