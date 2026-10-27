"""Indian market calendar: IST time helpers, NSE holidays, and trading calendar.

A standalone, dependency-injected market-calendar for NSE. It imports nothing
project-specific: each host project hands it a holiday-cache path (and an
optional logger) once at startup via ``configure()``.

Public API (see ``__all__``):
  Time      — IST, MARKET_OPEN, MARKET_CLOSE, now, today, is_after_market_close
  Holidays  — load_holidays (saved list only, never the network),
              reload_holidays (re-read a file another process saved),
              refresh_holidays (NSE fetch, merged by year, saved atomically),
              holiday_cache_path
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

import pandas as pd
import requests

__all__ = [
    "IST",
    "MARKET_OPEN",
    "MARKET_CLOSE",
    "now",
    "today",
    "is_after_market_close",
    "load_holidays",
    "reload_holidays",
    "refresh_holidays",
    "holiday_cache_path",
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
    The remembered holiday list is dropped: it came from the previous file.
    """
    global _cache_path, _logger, _cached_holidays, _load_failed_on
    _cache_path = Path(cache_path)
    _logger = logger if logger is not None else logging.getLogger("indian_market_calendar")
    with _cache_lock:
        _cached_holidays = None
        _load_failed_on = None


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
# Holidays (saved pickle read by questions; NSE fetched only by refresh)
# --------------------------------------------------------------------------- #
_cache_lock = threading.Lock()
_cached_holidays: list[date] | None = None
_load_failed_on: date | None = None  # IST date of the last failed file read

_NSE_HOME = "https://www.nseindia.com"
_NSE_HOLIDAYS_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_NSE_TIMEOUT = (3.05, 27)  # (connect, read) seconds, per request
_NSE_TOTAL_LIMIT = 60  # seconds for the whole download, however slowly NSE sends
_NSE_HEADERS = {  # browser headers, as nsepython sends them
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-US,en;q=0.9,en-IN;q=0.8,en-GB;q=0.7",
    "cache-control": "max-age=0",
    "priority": "u=0, i",
    "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
}


def holiday_cache_path() -> Path:
    """The configured holiday-cache file."""
    if _cache_path is None:
        raise RuntimeError(
            "indian_market_calendar is not configured: call "
            "configure(cache_path=...) first."
        )
    return _cache_path


def _read_cache_file(path: Path) -> list[date]:
    with open(path, "rb") as f:
        holidays = pickle.load(f)
    return pd.to_datetime(holidays).dt.date.tolist()


def load_holidays() -> list[date]:
    """Return the saved NSE holiday list; never touches the network.

    Read from the cache file once and kept in memory. With no readable file,
    returns ``[]`` and logs one error per IST date, retrying the file next date.
    """
    global _cached_holidays, _load_failed_on
    path = holiday_cache_path()
    cached = _cached_holidays
    if cached is not None:
        return cached
    with _cache_lock:
        if _cached_holidays is not None:
            return _cached_holidays
        anchor = today()
        if _load_failed_on == anchor:
            return []
        try:
            _cached_holidays = _read_cache_file(path)
        except Exception as cache_err:
            _get_logger().error(f"holiday cache load failed: {cache_err}")
            _load_failed_on = anchor
            return []
        return _cached_holidays


def reload_holidays() -> None:
    """Re-read the saved holiday file and use it; on a failure the remembered list stays and the error is raised."""
    global _cached_holidays, _load_failed_on
    holidays = _read_cache_file(holiday_cache_path())
    with _cache_lock:
        _cached_holidays = holidays
        _load_failed_on = None


def _fetch_nse_holidays() -> dict:
    """NSE's trading-holiday answer; cookies from the home page first, each request time-limited."""
    with requests.Session() as s:
        s.headers.update(_NSE_HEADERS)
        s.get(_NSE_HOME, timeout=_NSE_TIMEOUT)
        r = s.get(_NSE_HOLIDAYS_URL, timeout=_NSE_TIMEOUT)
        r.raise_for_status()
        return r.json()


def _fetch_nse_holidays_capped() -> dict:
    """``_fetch_nse_holidays`` given up after ``_NSE_TOTAL_LIMIT`` s.

    requests' timeouts only bound the gap between bytes, so the download runs in
    a daemon thread; one still running at the cap is abandoned, not waited for.
    """
    outcome: dict = {}

    def run():
        try:
            outcome["answer"] = _fetch_nse_holidays()
        except BaseException as e:
            outcome["error"] = e

    worker = threading.Thread(target=run, name="nse-holiday-fetch", daemon=True)
    worker.start()
    worker.join(_NSE_TOTAL_LIMIT)
    if worker.is_alive():
        raise requests.Timeout(f"NSE holiday download took over {_NSE_TOTAL_LIMIT} s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["answer"]


def refresh_holidays() -> bool:
    """Fetch NSE's holiday list, merge it by year, save it and use it.

    The answer's years replace their own dates; kept dates of other years stay.
    On a failed or empty answer the kept list stays and ``False`` is returned.
    No lock is held while NSE is called.
    """
    global _cached_holidays
    path = holiday_cache_path()
    try:
        answer = _fetch_nse_holidays_capped()
        fetched = pd.to_datetime(pd.DataFrame(answer["CM"])["tradingDate"]).dt.date.tolist()
        if not fetched:
            raise ValueError("empty holiday list")
    except Exception as e:
        _get_logger().warning(f"NSE holiday API failed: {e}")
        load_holidays()
        return False
    kept = _cached_holidays
    if kept is None:
        try:
            kept = _read_cache_file(path)
        except Exception:
            kept = []
    years = {d.year for d in fetched}
    merged = sorted({d for d in kept if d.year not in years} | set(fetched))
    saved = pd.Series([d.strftime("%d-%b-%Y") for d in merged])
    _atomic_write_bytes(pickle.dumps(saved), path)
    with _cache_lock:
        _cached_holidays = merged
    return True


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
