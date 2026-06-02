"""Tests for next_fire_at (patches the package's own collaborators)."""
import datetime as dt
from datetime import time

import indian_market_calendar as imc
from indian_market_calendar import IST, next_fire_at


def _t(y, m, d, h, minute=0):
    return dt.datetime(y, m, d, h, minute, tzinfo=IST)


def test_same_day_future_target(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    now = _t(2026, 4, 24, 7, 30)
    assert next_fire_at(time(9, 0), now=now) == _t(2026, 4, 24, 9, 0)


def test_same_day_past_target_rolls_to_next_trading_day(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(imc, "next_trading_day", lambda d: d + dt.timedelta(days=3))
    now = _t(2026, 4, 24, 10, 30)
    assert next_fire_at(time(9, 0), now=now) == _t(2026, 4, 27, 9, 0)


def test_non_trading_day_rolls_forward(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: False)
    monkeypatch.setattr(imc, "next_trading_day", lambda d: d + dt.timedelta(days=2))
    now = _t(2026, 4, 25, 7, 0)  # Saturday
    assert next_fire_at(time(9, 0), now=now) == _t(2026, 4, 27, 9, 0)
