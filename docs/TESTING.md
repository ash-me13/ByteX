# Testing ByteX

Run from the repository root. Safe tests need no network, no browser and no running backend.

## 1. Safe unit tests (stdlib only; no side effects)
```
PYTHONPATH=backend python3 -m unittest tests.test_local_guard tests.test_phone_pairing_lifecycle tests.test_app_wiring_static
```
They use temporary directories and a fake clock and never touch `backend/storage/trusted_phone_devices.json`.

## 2. Backend unit tests (need `pip install -r requirements.txt`; use the project `.venv`)
`tests/test_applescript_security.py`, `test_browser_discovery_macos.py`, `test_clipboard_truthful_reporting.py`,
`test_deletion_safety_regression.py`, `test_read_file_tool_execution_regression.py` and the `*_e2e.py` files in `tests/`.
The `*_e2e.py` files exercise coding/file/terminal skills: read each before running; run only on a throwaway workspace. (Not re-run in the 2026-10-26 audit: dependencies could not be installed there.)

## 3. Live tests: need a running backend and DO change state (`scratch/`)
`scratch/test_live_*.py`, `scratch/test_websocket_e2e_suite.py`, `scratch/test_feature_38_1_and_37_suite.py`, `scratch/verify_live_running_bytex.py`
connect to `127.0.0.1:8000`. The phone suite registers devices; that is how test devices ended up in your real trusted-device store.
Start a **separate** backend with an isolated store before running them:
```
BYTEX_STORAGE_DIR=$(mktemp -d) .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
(`BYTEX_STORAGE_DIR` redirects the trusted-device store only; task history, memory DB and action logs still use their own paths.)

## 4. Security-sensitive / PC-control tests
`scratch/test_feature_30_*`, `32_*`, `33_*` (automation, browser control, terminal, code execution) can launch apps, run compilers and drive a browser. Do not run them against your real session.

## Frontend
`cd ByteX && node_modules/.bin/tsc -b` (type-check), `npm run lint` (oxlint), `npm run build`.
Speech/command debugging: `localStorage.setItem('bytex_debug','1')` in the browser console, then reload (off by default; logs lengths/states, never text).

## Cleaning test devices from the trusted store (manual, needs your approval)
1. Stop the backend. 2. `cp backend/storage/trusted_phone_devices.json backend/storage/trusted_phone_devices.json.bak`
3. Remove the entries whose `device_name` you do not recognise (the audit saw `android_pixel_001` and `android_test_fix_001`). 4. Start the backend and check Settings > Phone.
