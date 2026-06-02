"""Tests for the session-window helpers."""
import datetime as dt

import indian_market_calendar as imc
from indian_market_calendar import (
    IST,
    is_in_session_window,
    next_session_window_open,
)


def _t(y, m, d, h, minute=0):
    return dt.datetime(y, m, d, h, minute, tzinfo=IST)


def test_window_open_close_times():
    assert imc._session_window_open_time() == dt.time(8, 45)
    assert imc._session_window_close_time() == dt.time(16, 30)


def test_in_window_at_boundaries(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    assert is_in_session_window(_t(2026, 4, 24, 8, 45))
    assert is_in_session_window(_t(2026, 4, 24, 9, 0))
    assert is_in_session_window(_t(2026, 4, 24, 16, 30))


def test_outside_window_at_boundaries(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    assert not is_in_session_window(_t(2026, 4, 24, 8, 44))
    assert not is_in_session_window(_t(2026, 4, 24, 16, 31))


def test_outside_window_on_non_trading_day(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: False)
    assert not is_in_session_window(_t(2026, 4, 25, 10, 0))


def test_next_session_window_open_before_window(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    now = _t(2026, 4, 24, 6, 0)
    assert next_session_window_open(now) == _t(2026, 4, 24, 8, 45)


def test_next_session_window_open_after_window(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(imc, "next_trading_day", lambda d: d + dt.timedelta(days=1))
    now = _t(2026, 4, 24, 17, 0)
    assert next_session_window_open(now) == _t(2026, 4, 25, 8, 45)


def test_next_session_window_open_skips_weekend(monkeypatch):
    monkeypatch.setattr(imc, "is_trading_day", lambda _d: False)
    monkeypatch.setattr(imc, "next_trading_day", lambda d: d + dt.timedelta(days=3))
    now = _t(2026, 4, 25, 10, 0)  # Saturday
    assert next_session_window_open(now) == _t(2026, 4, 28, 8, 45)
