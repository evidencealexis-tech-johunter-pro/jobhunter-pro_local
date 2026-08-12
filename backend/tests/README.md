# JobHunter Pro - Backend Test Suite

## What this is

A starting automated test suite, built specifically around real bugs found
during manual testing this session. Every test file exists because
something actually broke - these are regression tests first, general
coverage second. That's intentional: the goal right now is making sure
the specific things that already bit us once can never silently come
back, not chasing 100% coverage on day one.

## Setup (one time)

```
cd backend
venv312\Scripts\activate
pip install -r requirements-dev.txt --break-system-packages
```

(drop `--break-system-packages` if you're not on the same setup that
needed it earlier)

## Running the tests

From the `backend` folder:

```
pytest
```

For more detail on what's running:

```
pytest -v
```

To run just one file while you're working on something specific:

```
pytest tests/test_prefilter.py -v
```

## What's covered right now

- `test_prefilter.py` - the pre-filter that once rejected 100% of jobs
  from a real source (WeWorkRemotely) because its descriptions were too
  short to judge fairly. Locks in the "not enough text, let it through"
  safety rule.
- `test_clear_all_route.py` - the FastAPI route-ordering bug where
  "Clear All Jobs" returned success but deleted nothing, because a
  generic route was registered before the specific one. Checks the
  actual database state, not just the HTTP response code.
- `test_retry_logic.py` - the retry loop that used to wait out a
  rate-limit delay and then give up anyway, because there was never a
  second attempt slot available. Simulates a call that fails twice then
  succeeds, and checks it actually gets the successful result.
- `test_notifications.py` - the notification history system, built after
  discovering toast messages disappeared while the user was away. Checks
  notifications are saved, listed newest-first, marked read, and cleared.
- `test_byok_keys.py` - the BYOK key-saving flow. Checks a key is
  validated against only the selected provider (not the old five-provider
  guessing loop), rejected keys return a clear message, and a model isn't
  frozen into storage unless the user explicitly chose one.

## What's NOT covered yet (being upfront about it)

- The full background scrape loop end-to-end (`run_scrape`) - this is the
  most complex function in the app and deserves its own dedicated test
  file with careful mocking of the scraper and LLM calls. Worth doing
  next.
- `scraper.py`'s actual HTTP-fetching functions - these hit real external
  sites, so they need mocked HTTP responses to test properly rather than
  calling the real internet during a test run.
- The frontend (`JobDiscovery.jsx`, `Settings.jsx`, etc.) - this suite is
  backend-only. Frontend testing (React Testing Library, Vitest) is a
  separate, later investment.

## Why this matters going forward

Every one of the five bugs these tests cover was found by manually
reading through terminal logs together - some of them took multiple
messages back and forth to pin down. Any one of them would have been
caught in under a second by running this suite. From here forward, the
practice worth building is: whenever a new real bug gets fixed, add one
test for it in the same sitting - the suite should always be growing
alongside the app, not maintained separately from it.