# ----------------------------------------------------------------------------
# test_resilience.py: fault-injection shakedown of the client's network layer.
#
# These tests deterministically reproduce the failure modes seen in the wild:
# server responses slower than the client timeout, and dropped keep-alive
# connections. They verify adafruit_requests' internal fresh-socket retry
# plus the client's own retry-with-backoff on top of it.
#
# The api fixture patches TIMEOUT=1s and RETRY_DELAY=0.05s; adafruit_requests
# itself attempts each request up to 2x internally, and Tesserae_API retries
# the whole request up to RETRIES(=3)x. So the client survives up to
# 3*2-1 = 5 consecutive transport failures on one call.
# ----------------------------------------------------------------------------

import pytest

from conftest import unpack, fetch_content


def test_dropped_keepalive_recovers_internally(api, server):
  """ one silently-closed connection is absorbed by adafruit_requests """
  api.token = server.token
  server.push_fault("status", "drop")
  code, resp = unpack(api.status({"battery_mv": 4000}))
  assert code == 200
  assert resp["next_poll_s"] == 30


def test_drop_storm_recovers_via_outer_retry(api, server):
  """ 3 consecutive drops exhaust the library's internal retry once
  (OutOfRetries) — the client's own retry layer must recover """
  api.token = server.token
  for _ in range(3):
    server.push_fault("status", "drop")
  code, _ = unpack(api.status({"battery_mv": 4000}))
  assert code == 200


def test_slow_server_recovers(api, server):
  """ two responses slower than the timeout, then a normal one """
  api.token = server.token
  server.push_fault("status", "stall", 1.5)   # > TIMEOUT of 1s
  server.push_fault("status", "stall", 1.5)
  code, _ = unpack(api.status({"battery_mv": 4000}))
  assert code == 200


def test_retries_eventually_exhausted(api, server):
  """ a permanently broken connection must still surface an error """
  api.token = server.token
  for _ in range(8):                          # > 3 outer x 2 inner attempts
    server.push_fault("status", "drop")
  with pytest.raises(Exception):
    api.status({"battery_mv": 4000})


def test_http_error_is_not_retried(api, server):
  """ a valid HTTP error (401) is an answer, not a transport failure —
  it must be returned immediately, without burning retries """
  api.token = "stale-token"
  server.push_fault("status", "respond", 401, {"error": "invalid token"})
  code, resp = unpack(api.status({"battery_mv": 4000}))
  assert code == 401
  assert server.count("/status") == 1


def test_truncated_content_detected(api, server):
  """ a short read of the dashboard must not be silently accepted """
  api.token = server.token
  api.frame()
  server.content_length_override = len(server.content) + 64
  with pytest.raises((RuntimeError, OSError)):
    fetch_content(api)
