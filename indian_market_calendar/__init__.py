"""Indian market calendar: IST time helpers, NSE holidays, and trading calendar.

A standalone, dependency-injected market-calendar for NSE. It imports nothing
project-specific: each host project hands it a holiday-cache path (and an
optional logger) once at startup via ``configure()``.

Public API (see ``__all__``):
  Time      — IST, MARKET_OPEN, MARKET_CLOSE, now, today, is_after_market_close
  Holidays  — load_holidays (NSE fetch + atomic pickle cache, memoized per IST date)
  Calendar  — is_trading_day, compute_last_trading_day, next_trading_day
  Market    — Market, is_market_open, next_fire_at, is_in_session_window,
              next_session_window_open, SESSION_WINDOW_* buffers
  Config    — configure(cache_path, logger=None)
"""

import contextlib
import datetime as dt
import enum
import logging
import os
import pickle
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import nsepython
import pandas as pd

__all__ = [
    "IST",
    "MARKET_OPEN",
    "MARKET_CLOSE",
    "now",
    "today",
    "is_after_market_close",
    "load_holidays",
    "is_trading_day",
    "compute_last_trading_day",
    "next_trading_day",
    "Market",
    "is_market_open",
    "next_fire_at",
    "is_in_session_window",
    "next_session_window_open",
    "SESSION_WINDOW_PRE_OPEN_BUFFER",
    "SESSION_WINDOW_POST_CLOSE_BUFFER",
    "configure",
]

# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now() -> datetime:
    return datetime.now(IST)


def today() -> date:
    return now().date()


def is_after_market_close() -> bool:
    return now().time() > MARKET_CLOSE


# --------------------------------------------------------------------------- #
# Dependency injection (cache path + logger)
# --------------------------------------------------------------------------- #
_cache_path: Path | None = None
_logger: logging.Logger | None = None


def configure(cache_path, logger=None) -> None:
    """Inject the host project's holiday-cache file path and optional logger.

    ``cache_path`` (required) is where the NSE holiday pickle is read/written.
    ``logger`` must be ``logging.Logger``-compatible — the package calls only
    ``logger.warning(msg)`` / ``logger.error(msg)``. When ``None`` the package
    falls back to ``logging.getLogger("indian_market_calendar")``.
    """
    global _cache_path, _logger
    _cache_path = Path(cache_path)
    _logger = logger if logger is not None else logging.getLogger("indian_market_calendar")


def _get_logger() -> logging.Logger:
    if _logger is not None:
        return _logger
    return logging.getLogger("indian_market_calendar")


# --------------------------------------------------------------------------- #
# Bundled atomic write (no host-project dependency)
# --------------------------------------------------------------------------- #
def _atomic_write_bytes(data: bytes, path: Path) -> None:
    """Write bytes to a temp file alongside ``path``, then rename over it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    try:
        tmp_path.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


# --------------------------------------------------------------------------- #
# Holidays (NSE fetch + atomic pickle cache, memoized per IST date)
# --------------------------------------------------------------------------- #
_cache_lock = threading.Lock()
_cached_holidays: list[date] | None = None
_cached_date: date | None = None


def _fetch_holidays() -> list[date]:
    """Fetch from NSE, persist to pickle, fall back to pickle on failure."""
    try:
        holidays = nsepython.holiday_master()
        holidays = pd.DataFrame(holidays["CM"])["tradingDate"]
        if not holidays.empty:
            _atomic_write_bytes(pickle.dumps(holidays), _cache_path)
        return pd.to_datetime(holidays).dt.date.tolist()
    except Exception as e:
        _get_logger().warning(f"NSE holiday API failed: {e}")
        try:
            with open(_cache_path, "rb") as f:
                holidays = pickle.load(f)
            return pd.to_datetime(holidays).dt.date.tolist()
        except Exception as cache_err:
            _get_logger().error(f"holiday cache load failed: {cache_err}")
            return []


def load_holidays() -> list[date]:
    """Return NSE holiday list, cached in-process per IST date."""
    if _cache_path is None:
        raise RuntimeError(
            "indian_market_calendar is not configured: call "
            "configure(cache_path=...) before load_holidays()."
        )
    global _cached_holidays, _cached_date
    anchor = today()
    cached = _cached_holidays
    if cached is not None and _cached_date == anchor:
        return cached
    with _cache_lock:
        if _cached_holidays is not None and _cached_date == anchor:
            return _cached_holidays
        _cached_holidays = _fetch_holidays()
        _cached_date = anchor
        return _cached_holidays


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
def is_trading_day(day: date) -> bool:
    """True iff ``day`` is an NSE trading day (weekday and not a holiday)."""
    if day.weekday() >= 5:
        return False
    return day not in load_holidays()


def next_trading_day(day: date) -> date:
    """Return the next NSE trading day strictly after ``day``."""
    holidays = load_holidays()
    nxt = day + dt.timedelta(1)
    while nxt.weekday() >= 5 or nxt in holidays:
        nxt += dt.timedelta(1)
    return nxt


def compute_last_trading_day() -> date:
    """Return the most recent completed NSE trading day."""
    holidays = load_holidays()
    anchor = today() if is_after_market_close() else today() - dt.timedelta(1)
    while anchor.weekday() >= 5 or anchor in holidays:
        anchor -= dt.timedelta(1)
    return anchor


# --------------------------------------------------------------------------- #
# Market / scheduling
# --------------------------------------------------------------------------- #
SESSION_WINDOW_PRE_OPEN_BUFFER: timedelta = timedelta(minutes=30)
SESSION_WINDOW_POST_CLOSE_BUFFER: timedelta = timedelta(minutes=60)


class Market(str, enum.Enum):
    NSE = "NSE"
    NYSE = "NYSE"


def is_market_open(
    now: datetime | None = None, *, market: Market = Market.NSE
) -> bool:
    """True iff the market is open at ``now`` (defaults to the current IST time).

    NSE is open from ``MARKET_OPEN`` through ``MARKET_CLOSE`` inclusive
    (``now.time() <= MARKET_CLOSE``) on trading days.
    """
    if market is Market.NYSE:
        raise NotImplementedError("NYSE calendar not implemented.")
    now = now if now is not None else globals()["now"]()
    if now.weekday() >= 5:
        return False
    if now.date() in load_holidays():
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def next_fire_at(target_time: time, now: datetime | None = None) -> datetime:
    """Return the next trading-day ``target_time`` (IST) strictly after ``now``.

    If today is a trading day and ``target_time`` today is strictly in the
    future, returns today. Otherwise rolls forward to the next trading day.
    """
    now = now if now is not None else globals()["now"]()
    anchor = now.date()
    if is_trading_day(anchor):
        fire = datetime.combine(anchor, target_time, tzinfo=IST)
        if fire > now:
            return fire
    nxt = next_trading_day(anchor)
    return datetime.combine(nxt, target_time, tzinfo=IST)


def _session_window_open_time() -> time:
    """``MARKET_OPEN`` minus ``SESSION_WINDOW_PRE_OPEN_BUFFER``."""
    base = datetime.combine(date.min, MARKET_OPEN)
    return (base - SESSION_WINDOW_PRE_OPEN_BUFFER).time()


def _session_window_close_time() -> time:
    """``MARKET_CLOSE`` plus ``SESSION_WINDOW_POST_CLOSE_BUFFER``."""
    base = datetime.combine(date.min, MARKET_CLOSE)
    return (base + SESSION_WINDOW_POST_CLOSE_BUFFER).time()


def is_in_session_window(now: datetime | None = None) -> bool:
    """True iff ``now`` is on a trading day inside the buffered session window."""
    now = now if now is not None else globals()["now"]()
    if not is_trading_day(now.date()):
        return False
    return _session_window_open_time() <= now.time() <= _session_window_close_time()


def next_session_window_open(now: datetime | None = None) -> datetime:
    """Next trading-day datetime at the window-open wall-clock time."""
    return next_fire_at(_session_window_open_time(), now=now)
