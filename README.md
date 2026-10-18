# indian-market-calendar

IST time helpers, NSE holiday loading, and an NSE trading calendar in one
standalone, dependency-injected module. It imports nothing project-specific:
each host project hands it a holiday-cache path (and an optional logger) once
at startup via `configure()`.

```python
import logging
from pathlib import Path
import indian_market_calendar as imc

imc.configure(cache_path=Path("/var/cache/nse_holidays.pkl"), logger=logging.getLogger("app"))
imc.refresh_holidays()         # fetch from NSE and save; call at start-up and daily, off the event loop

imc.now()                      # tz-aware IST datetime
imc.today()                    # IST date
imc.is_trading_day(imc.today())
imc.is_market_open()           # open 09:15–15:30 IST inclusive on trading days
imc.compute_last_trading_day()
imc.next_trading_day(imc.today())
imc.next_fire_at(imc.MARKET_OPEN)
imc.is_in_session_window()
imc.next_session_window_open()
```

## Public API

- **Time:** `IST`, `MARKET_OPEN`, `MARKET_CLOSE`, `now()`, `today()`, `is_after_market_close()`
- **Holidays:**
  - `load_holidays()` — the saved list only, never the network: the cache file is read once and kept in memory; with no readable file it returns `[]` (every weekday a trading day) and logs one error per IST date.
  - `refresh_holidays() -> bool` — fetches NSE's list with no lock held, merges it by year (the answer's years replace their own dates; other years' saved dates stay), saves it atomically and uses it. On a failed or empty answer the saved list stays and it returns `False`. Nothing calls it for you: the host calls it at start-up and on its own schedule.
  - `holiday_cache_path()` — the configured cache file.
- **Calendar:** `is_trading_day(day)`, `compute_last_trading_day()`, `next_trading_day(day)`
- **Market / scheduling:** `Market`, `is_market_open(now=None, *, market=NSE)`, `next_fire_at(target_time, now=None)`, `is_in_session_window(now=None)`, `next_session_window_open(now=None)`, `SESSION_WINDOW_PRE_OPEN_BUFFER`, `SESSION_WINDOW_POST_CLOSE_BUFFER`
- **Config:** `configure(cache_path, logger=None)` — also drops the remembered holiday list

`is_market_open` treats NSE as open from `MARKET_OPEN` through `MARKET_CLOSE`
**inclusive** (`now.time() <= MARKET_CLOSE`). `Market.NYSE` raises
`NotImplementedError`.

## Tests

```bash
pip install -e ".[test]"
pytest
```
