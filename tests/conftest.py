"""Shared fixtures for the indian_market_calendar test suite."""
import pytest

import indian_market_calendar as imc


@pytest.fixture(autouse=True)
def _configured(tmp_path, monkeypatch):
    """Configure the package with a throwaway cache path and reset the
    in-process holiday cache before every test."""
    imc.configure(cache_path=tmp_path / "nse_holidays.pkl")
    monkeypatch.setattr(imc, "_cached_holidays", None, raising=False)
    monkeypatch.setattr(imc, "_cached_date", None, raising=False)
    yield
