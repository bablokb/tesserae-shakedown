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
  # clients without the retry feature have no RETRY_DELAY; setting it is
  # harmless there and the resilience tests will document the gap
  monkeypatch.setattr(tesserae_api.Tesserae_API, "RETRY_DELAY", 0.05,
                      raising=False)
  # newer clients added rotation/format to the identity — adapt by signature
  import inspect
  id_params = inspect.signature(tesserae_api.Tesserae_ID.__init__).parameters
  kwargs = dict(name="Shakedown", device_id="shakedown_dev",
                width=400, height=300, gamut="rgb24",
                mac="02:00:00:00:00:01")
  if "rotation" in id_params:
    kwargs["rotation"] = 0
  if "format" in id_params:
    kwargs["format"] = "bmp"
  ident = tesserae_api.Tesserae_ID(**kwargs)
  return tesserae_api.Tesserae_API(ident.id, server.url, session, debug=False)


# --- cross-generation compatibility helpers ---------------------------------
# older clients return (code, resp); newer ones return (code, headers, resp)

def unpack(result):
  if isinstance(result, tuple) and len(result) == 3:
    return result[0], result[2]
  return result


def fetch_content(api):
  """ normalize url_content across client generations: return bytes.
  old: returns a filled buffer; new: streams into a provided io object """
  import inspect
  import io
  if "io_obj" in inspect.signature(api.url_content).parameters:
    out = api.url_content(io.BytesIO())
    return out.getvalue()
  return bytes(api.url_content())
