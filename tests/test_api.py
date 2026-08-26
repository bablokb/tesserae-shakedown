# ----------------------------------------------------------------------------
# test_api.py: happy-path shakedown of the Tesserae_API client layer.
#
# Covers: discovery (registered + pending), pairing-code registration,
# frame fetch with ETag/304 caching, auth-header handling, status posting
# and dashboard content download integrity.
# ----------------------------------------------------------------------------

import pytest


# --- registration & auth ----------------------------------------------------

def test_discover_registered(api, server):
  code, resp = api.discover()
  assert code == 200
  assert resp["registered"] is True
  assert api.token == server.token


def test_discover_pending_approval(api, server):
  server.discover_response = {"registered": False, "retry_after_s": 42}
  code, resp = api.discover()
  assert code == 200
  assert resp["registered"] is False
  assert resp["retry_after_s"] == 42
  assert api.token is None


def test_register_with_pairing_code(api, server):
  code, resp = api.register("123456")
  assert code == 201
  assert api.token == server.token
  headers = server.headers_for("/register")[0]
  assert headers.get("x-pairing-code") == "123456"


def test_authed_call_without_token_fails_fast(api, server):
  with pytest.raises(RuntimeError):
    api.status({"battery_mv": 3000})
  # the client must not have sent anything to the server
  assert server.count("/status") == 0


# --- frame / ETag caching ---------------------------------------------------

def test_frame_etag_flow(api, server):
  api.token = server.token

  code, resp = api.frame()
  assert code == 200
  assert resp["url"] == server.content_url

  code2, resp2 = api.frame()
  assert code2 == 304
  # the client synthesizes the url from the cached Content-Location on 304
  assert resp2["url"] == server.content_url

  frames = server.headers_for("/frame")
  assert "if-none-match" not in frames[0]
  assert frames[1].get("if-none-match") == server.etag
  assert frames[0].get("x-tesserae-token") == server.token


def test_frame_refetches_after_etag_change(api, server):
  api.token = server.token
  code, _ = api.frame()
  assert code == 200
  server.etag = "etag-v2"          # server-side content changed
  code2, _ = api.frame()
  assert code2 == 200              # stale If-None-Match must not yield a 304


# --- status -----------------------------------------------------------------

def test_status_returns_poll_interval(api, server):
  api.token = server.token
  code, resp = api.status({"battery_mv": 4200})
  assert code == 200
  assert resp["next_poll_s"] == 30
  headers = server.headers_for("/status")[0]
  assert headers.get("x-tesserae-token") == server.token


# --- dashboard content download ---------------------------------------------

def test_url_content_integrity(api, server):
  api.token = server.token
  api.frame()
  buffer = api.url_content()
  assert bytes(buffer) == server.content


def test_url_content_requires_prior_frame(api):
  with pytest.raises(RuntimeError):
    api.url_content()
