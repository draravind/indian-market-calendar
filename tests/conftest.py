"""Shared fixtures for the indian_market_calendar test suite."""
import nsepython
import pytest

import indian_market_calendar as imc


@pytest.fixture(autouse=True)
def _configured(tmp_path, monkeypatch):
    """Configure the package with a throwaway cache path and reset the
    in-process holiday cache before every test."""
    imc.configure(cache_path=tmp_path / "nse_holidays.pkl")
    monkeypatch.setattr(imc, "_cached_holidays", None, raising=False)
    monkeypatch.setattr(imc, "_load_failed_on", None, raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_nse(monkeypatch):
    """NSE is never reached from a test; a test wanting an answer patches its own."""

    def unreachable():
        raise RuntimeError("NSE is not reachable from tests")

    monkeypatch.setattr(nsepython, "holiday_master", unreachable)
