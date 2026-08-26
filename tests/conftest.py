# ----------------------------------------------------------------------------
# conftest.py: shared fixtures for the Tesserae client shakedown tests.
#
# Imports the REAL client code (tesserae_api.py and the GENERIC_LINUX_PC HAL)
# from the client checkout, located via TESSERAE_CLIENT_DIR (defaults to a
# sibling "tesserae-device-circuitpython" directory).
# ----------------------------------------------------------------------------

import os
import socket
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_DIR = os.environ.get(
  "TESSERAE_CLIENT_DIR",
  os.path.join(os.path.dirname(_REPO_ROOT), "tesserae-device-circuitpython"))

if not os.path.isdir(CLIENT_DIR):
  raise RuntimeError(
    f"client checkout not found at {CLIENT_DIR} — set TESSERAE_CLIENT_DIR")

# Blinka cannot detect macOS; same forced identity the client itself uses
os.environ.setdefault("BLINKA_FORCEBOARD", "GENERIC_LINUX_PC")
os.environ.setdefault("BLINKA_FORCECHIP", "GENERIC_X86")

sys.path.insert(0, os.path.join(CLIENT_DIR, "external", "tesserae_api"))

import tesserae_api  # noqa: E402  (needs sys.path set up first)

from fake_server import FakeTesseraeServer  # noqa: E402


@pytest.fixture
def server():
  srv = FakeTesseraeServer()
  srv.start()
  yield srv
  srv.stop()


@pytest.fixture
def session():
  """ an adafruit_requests session built exactly like the client HAL does """
  import adafruit_requests
  sess = adafruit_requests.Session(socket)
  yield sess
  # drop pooled sockets so one test's dead connections can't leak into the next
  try:
    import adafruit_connection_manager
    adafruit_connection_manager.connection_manager_close_all(socket)
  except Exception:
    pass


@pytest.fixture
def api(server, session, monkeypatch):
  """ a Tesserae_API instance pointed at the fake server, with short
  timeouts so fault tests run fast """
  monkeypatch.setattr(tesserae_api.Tesserae_API, "TIMEOUT", 1)
  monkeypatch.setattr(tesserae_api.Tesserae_API, "RETRY_DELAY", 0.05)
  ident = tesserae_api.Tesserae_ID(
    "Shakedown", "shakedown_dev", 400, 300, "rgb24", "02:00:00:00:00:01")
  return tesserae_api.Tesserae_API(ident.id, server.url, session, debug=False)
