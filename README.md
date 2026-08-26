# tesserae-shakedown

Automated shakedown harness for the [Tesserae CircuitPython client](https://github.com/bablokb/tesserae-device-circuitpython)
running in desktop emulation (macOS/Linux).

Built while testing the macOS install path — findings and results in
[dmellok/tesserae discussion #24](https://github.com/dmellok/tesserae/discussions/24).

## What it covers

**Tier 1 — deterministic API & unit tests** (`tests/`, pytest, no display, no
real server). Runs the *real* client code (`tesserae_api.py`, the
`GENERIC_LINUX_PC` HAL) against a scriptable fake Tesserae server:

- discovery (registered + pending-approval responses)
- pairing-code registration (header handling)
- frame fetch with ETag caching: 200 → 304, re-fetch after server-side change
- auth token header, fail-fast when no token is set
- status POST and `next_poll_s` handling
- dashboard content download integrity (chunked read, length check,
  truncation detection)
- network resilience: dropped keep-alive connections, responses slower than
  the client timeout, retry exhaustion, and no-retry on valid HTTP errors
  (e.g. 401)
- NVRAM token store: round-trip of the magic+length+token framing,
  fresh-install behavior, magic-number invalidation

**Tier 2 — headless end-to-end smoke** (`smoke/run_once.py`). Runs one real
client cycle per display type against the *real* server with the SDL dummy
video driver (no window), classifies the outcome and saves the rendered
framebuffer as a PNG:

- `OK` — registered, dashboard fetched and painted (or valid 304 no-repaint)
- `PENDING` — device unknown to the server, awaiting admin approval
- `FAIL` — anything else (log captured)

## Not covered (manual)

- admin approval of newly discovered devices (server-side action)
- issuing pairing codes (server-side action)
- "window actually appears on screen" on macOS — run windowed to verify:
  `SHAKEDOWN_WINDOWED=1 TESSERAE_DISPLAY=native ./smoke/run_once.py ...`

## Usage

```sh
./shakedown.sh                             # tier 1 + smoke of "native"
SHAKEDOWN_DISPLAYS=all ./shakedown.sh      # smoke all 11 display types
SHAKEDOWN_DISPLAYS=native,sharp400 ./shakedown.sh
SHAKEDOWN_SKIP_SMOKE=1 ./shakedown.sh      # tier 1 only
```

Results land in `report/<timestamp>/`: `report.md`, per-tier logs, and one
PNG per display type that painted.

## Configuration

| variable | default | meaning |
|---|---|---|
| `TESSERAE_CLIENT_DIR` | `../tesserae-device-circuitpython` | client checkout to test |
| `SHAKEDOWN_DISPLAYS` | `native` | comma list or `all` |
| `SHAKEDOWN_SKIP_SMOKE` | unset | tier 1 only |
| `SHAKEDOWN_CYCLE_TIMEOUT` | `90` | seconds before a smoke cycle is killed |
| `SHAKEDOWN_WINDOWED` | unset | show the real pygame window during smoke |

Tier 1 uses its own venv (`venv.shakedown`, created on first run). Tier 2
reuses the client's `venv.tesserae.cp-client`.

Note: smoke runs for display types other than `native` register new devices
(`cp_<type>`) on the server; until approved there, they report `PENDING` —
that's expected, not a failure.
