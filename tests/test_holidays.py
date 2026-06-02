"""Tests for load_holidays caching and configure() guard."""
import datetime as dt

import pytest

import indian_market_calendar as imc
from indian_market_calendar import load_holidays


class TestCaching:
    def test_one_fetch_per_ist_date(self, monkeypatch):
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return [dt.date(2025, 3, 14)]

        monkeypatch.setattr(imc, "_fetch_holidays", fake_fetch)
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 12))

        first = load_holidays()
        second = load_holidays()
        third = load_holidays()
        assert first == second == third == [dt.date(2025, 3, 14)]
        assert calls["n"] == 1  # memoized within the same IST date

    def test_refetch_on_new_ist_date(self, monkeypatch):
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return [dt.date(2025, 3, 14)]

        monkeypatch.setattr(imc, "_fetch_holidays", fake_fetch)

        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 12))
        load_holidays()
        monkeypatch.setattr(imc, "today", lambda: dt.date(2025, 3, 13))
        load_holidays()
        assert calls["n"] == 2  # one fetch per distinct IST date


class TestConfigureGuard:
    def test_raises_when_cache_path_unset(self, monkeypatch):
        monkeypatch.setattr(imc, "_cache_path", None, raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            load_holidays()
