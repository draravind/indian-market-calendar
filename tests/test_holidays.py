"""Tests for load_holidays (saved list only), refresh_holidays and configure()."""
import datetime as dt
import logging
import pickle
import threading
import time

import pandas as pd
import pytest
import requests

import indian_market_calendar as imc
from indian_market_calendar import load_holidays

LIST_2026 = [dt.date(2026, 1, 26), dt.date(2026, 10, 20), dt.date(2026, 12, 25)]


def _save(path, days):
    """Write ``days`` in NSE's saved shape: a Series of ``%d-%b-%Y`` strings."""
    path.write_bytes(pickle.dumps(pd.Series([d.strftime("%d-%b-%Y") for d in days])))


def _saved(path):
    return pd.to_datetime(pickle.loads(path.read_bytes())).dt.date.tolist()


def _answer(*trading_dates):
    """NSE's holiday-master answer for these ``%d-%b-%Y`` dates."""
    return {"CM": [{"tradingDate": d} for d in trading_dates]}


@pytest.fixture
def cache_file():
    return imc.holiday_cache_path()


@pytest.fixture
def nse_calls(monkeypatch):
    """Record every NSE call; tests set ``answer`` (a dict, or an exception to raise)."""
    record = {"calls": 0, "answer": RuntimeError("NSE unreachable")}

    def fake_fetch():
        record["calls"] += 1
        if isinstance(record["answer"], BaseException):
            raise record["answer"]
        return record["answer"]

    monkeypatch.setattr(imc, "_fetch_nse_holidays", fake_fetch)
    return record


class TestLoadNeverFetches:
    def test_load_never_calls_nse(self, monkeypatch, cache_file, nse_calls):
        _save(cache_file, LIST_2026)
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 10, 19))
        assert load_holidays() == LIST_2026
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 10, 20))
        assert load_holidays() == LIST_2026
        assert nse_calls["calls"] == 0

    def test_no_file_answers_empty_without_nse(self, nse_calls):
        assert load_holidays() == []
        assert nse_calls["calls"] == 0

    def test_no_file_logs_one_error_per_date(self, monkeypatch, caplog):
        caplog.set_level(logging.ERROR, logger="indian_market_calendar")
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 10, 19))
        assert load_holidays() == []
        assert load_holidays() == []
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 10, 20))
        assert load_holidays() == []
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 2
        assert all(m.startswith("holiday cache load failed") for m in errors)


class TestRefresh:
    def test_refresh_saves_and_replaces(self, cache_file, nse_calls):
        _save(cache_file, LIST_2026)
        assert load_holidays() == LIST_2026
        nse_calls["answer"] = _answer("26-Jan-2026", "03-Mar-2026")
        assert imc.refresh_holidays() is True
        expected = [dt.date(2026, 1, 26), dt.date(2026, 3, 3)]
        assert load_holidays() == expected
        assert _saved(cache_file) == expected

    @pytest.mark.parametrize(
        "answer",
        [RuntimeError("NSE down"), {}, {"CM": []}, {"CM": [{"other": 1}]}, "garbled"],
        ids=["raises", "no-CM", "empty-CM", "no-tradingDate", "garbled"],
    )
    def test_failed_refresh_keeps_the_list(self, cache_file, nse_calls, caplog, answer):
        caplog.set_level(logging.WARNING, logger="indian_market_calendar")
        _save(cache_file, LIST_2026)
        before = cache_file.read_bytes()
        nse_calls["answer"] = answer
        assert imc.refresh_holidays() is False
        assert load_holidays() == LIST_2026
        assert cache_file.read_bytes() == before
        assert any(r.getMessage().startswith("NSE holiday API failed") for r in caplog.records)

    def test_question_during_slow_refresh_answers_from_the_file(self, monkeypatch, cache_file):
        """Row 10: a question while NSE takes 1 s is answered at once from the saved file."""
        _save(cache_file, LIST_2026)
        inside = threading.Event()

        def slow_fetch():
            inside.set()
            time.sleep(1.0)
            return _answer("26-Jan-2026")

        monkeypatch.setattr(imc, "_fetch_nse_holidays", slow_fetch)
        refresher = threading.Thread(target=imc.refresh_holidays)
        refresher.start()
        try:
            assert inside.wait(5)
            started = time.monotonic()
            assert load_holidays() == LIST_2026
            assert time.monotonic() - started < 0.1
        finally:
            refresher.join(5)

    def test_question_during_hung_refresh_with_no_file_counts_weekdays_open(self, monkeypatch):
        """Row 11: no file, NSE hung → answered at once, weekdays open."""
        inside, release = threading.Event(), threading.Event()

        def hung_fetch():
            inside.set()
            release.wait(5)
            raise RuntimeError("NSE hung")

        monkeypatch.setattr(imc, "_fetch_nse_holidays", hung_fetch)
        refresher = threading.Thread(target=imc.refresh_holidays)
        refresher.start()
        try:
            assert inside.wait(5)
            started = time.monotonic()
            assert imc.is_trading_day(dt.date(2026, 10, 20)) is True
            assert time.monotonic() - started < 0.1
        finally:
            release.set()
            refresher.join(5)

    def test_answer_missing_a_kept_year_keeps_that_year(self, monkeypatch, cache_file, nse_calls):
        """Row 21: a 2027-only answer keeps the kept 2026 dates."""
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 12, 20))
        _save(cache_file, LIST_2026)
        nse_calls["answer"] = _answer("26-Jan-2027")
        assert imc.refresh_holidays() is True
        assert imc.is_trading_day(dt.date(2026, 12, 25)) is False
        assert imc.is_trading_day(dt.date(2027, 1, 26)) is False
        assert _saved(cache_file) == LIST_2026 + [dt.date(2027, 1, 26)]

    def test_answer_replaces_its_own_year(self, cache_file, nse_calls):
        """Row 21: the answer's year replaces that year's kept dates."""
        _save(cache_file, [dt.date(2027, 1, 26)])
        nse_calls["answer"] = _answer("15-Jan-2027")
        assert imc.refresh_holidays() is True
        assert imc.is_trading_day(dt.date(2027, 1, 26)) is True
        assert imc.is_trading_day(dt.date(2027, 1, 15)) is False


class _FakeResponse:
    def __init__(self, answer):
        self._answer = answer

    def raise_for_status(self):
        pass

    def json(self):
        return self._answer


class _FakeSession:
    """``requests.Session`` stand-in: records each ``get``; ``fail_api`` makes the API request raise."""

    gets: list = []
    answer: dict = {}
    fail_api: BaseException | None = None

    def __init__(self):
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, timeout=None):
        type(self).gets.append((url, timeout))
        fail = type(self).fail_api
        if "/api/" in url and fail is not None:
            raise fail
        return _FakeResponse(type(self).answer)


class TestFetch:
    """The NSE download itself: every request is time-limited."""

    @pytest.fixture(autouse=True)
    def _no_nse(self, monkeypatch):
        """Overrides the suite's guard: the real download runs against a fake session."""
        monkeypatch.setattr(_FakeSession, "gets", [])
        monkeypatch.setattr(_FakeSession, "answer", _answer("26-Jan-2026"))
        monkeypatch.setattr(_FakeSession, "fail_api", None)
        monkeypatch.setattr(imc.requests, "Session", _FakeSession)

    def test_every_request_carries_the_time_limit(self):
        assert imc._fetch_nse_holidays() == _answer("26-Jan-2026")
        assert _FakeSession.gets == [
            ("https://www.nseindia.com", (3.05, 27)),
            ("https://www.nseindia.com/api/holiday-master?type=trading", (3.05, 27)),
        ]

    def test_whole_download_is_capped_at_sixty_seconds(self):
        assert imc._NSE_TOTAL_LIMIT == 60

    def test_trickling_download_is_cut_off_and_keeps_the_list(self, monkeypatch, cache_file):
        """NSE sends a byte now and then, never finishing: the refresh gives up at the cap."""
        _save(cache_file, LIST_2026)
        before = cache_file.read_bytes()
        release = threading.Event()

        def trickling_fetch():
            release.wait(5)
            return _answer("26-Jan-2026")

        monkeypatch.setattr(imc, "_fetch_nse_holidays", trickling_fetch)
        monkeypatch.setattr(imc, "_NSE_TOTAL_LIMIT", 0.2)
        try:
            started = time.monotonic()
            assert imc.refresh_holidays() is False
            assert time.monotonic() - started < 2
        finally:
            release.set()
        assert load_holidays() == LIST_2026
        assert cache_file.read_bytes() == before

    def test_download_inside_the_cap_is_used(self, monkeypatch, cache_file):
        monkeypatch.setattr(imc, "_NSE_TOTAL_LIMIT", 5)
        assert imc.refresh_holidays() is True
        assert _saved(cache_file) == [dt.date(2026, 1, 26)]

    def test_timeout_fails_the_refresh_and_keeps_the_list(self, cache_file):
        _save(cache_file, LIST_2026)
        before = cache_file.read_bytes()
        _FakeSession.fail_api = requests.Timeout("read timed out")
        assert imc.refresh_holidays() is False
        assert load_holidays() == LIST_2026
        assert cache_file.read_bytes() == before


class TestReload:
    """A reader picking up a file another process saved."""

    def test_reload_replaces_the_remembered_list(self, cache_file):
        _save(cache_file, LIST_2026)
        assert load_holidays() == LIST_2026
        _save(cache_file, [dt.date(2027, 1, 26)])
        imc.reload_holidays()
        assert load_holidays() == [dt.date(2027, 1, 26)]

    def test_broken_file_raises_and_keeps_the_old_list(self, cache_file):
        _save(cache_file, LIST_2026)
        assert load_holidays() == LIST_2026
        cache_file.write_bytes(b"not a pickle")
        with pytest.raises(pickle.UnpicklingError):
            imc.reload_holidays()
        assert load_holidays() == LIST_2026

    def test_missing_file_with_nothing_remembered_raises_and_answers_empty(self):
        with pytest.raises(FileNotFoundError):
            imc.reload_holidays()
        assert load_holidays() == []

    def test_junk_file_with_nothing_remembered_counts_weekdays_open(self, cache_file):
        cache_file.write_bytes(b"\x00\x01junk")
        with pytest.raises(pickle.UnpicklingError):
            imc.reload_holidays()
        assert load_holidays() == []
        assert imc.is_trading_day(dt.date(2026, 10, 20)) is True

    def test_reload_ends_todays_failed_load(self, monkeypatch, cache_file):
        monkeypatch.setattr(imc, "today", lambda: dt.date(2026, 10, 19))
        assert load_holidays() == []
        _save(cache_file, LIST_2026)
        imc.reload_holidays()
        assert load_holidays() == LIST_2026


class TestConfigure:
    def test_reconfigure_forgets_the_remembered_list(self, tmp_path, cache_file):
        _save(cache_file, LIST_2026)
        assert load_holidays() == LIST_2026
        imc.configure(cache_path=tmp_path / "missing" / "nse_holidays.pkl")
        assert load_holidays() == []

    def test_holiday_cache_path_is_the_configured_path(self, tmp_path):
        imc.configure(cache_path=tmp_path / "elsewhere.pkl")
        assert imc.holiday_cache_path() == tmp_path / "elsewhere.pkl"

    def test_holiday_cache_path_raises_when_unset(self, monkeypatch):
        monkeypatch.setattr(imc, "_cache_path", None, raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            imc.holiday_cache_path()


class TestConfigureGuard:
    def test_raises_when_cache_path_unset(self, monkeypatch):
        monkeypatch.setattr(imc, "_cache_path", None, raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            load_holidays()
