# ----------------------------------------------------------------------------
# fake_server.py: scriptable stand-in for the Tesserae server REST-API.
#
# Serves the endpoints the CircuitPython client uses (discover, register,
# frame, status, log, content download) and lets tests inject faults per
# endpoint: stalls (to trip the client timeout), silent connection closes
# (to simulate dropped keep-alives) and scripted responses (e.g. 401).
# ----------------------------------------------------------------------------

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_ROOT = "/api/v1/device"


class _Handler(BaseHTTPRequestHandler):
  protocol_version = "HTTP/1.1"

  def log_message(self, *args):
    pass

  # --- fault injection ------------------------------------------------------

  def _apply_fault(self, key):
    """ pop and apply the next scripted fault for this endpoint.
    Returns True if the fault fully handled the request. """
    queue = self.server.faults.get(key)
    if not queue:
      return False
    fault = queue.pop(0)
    kind = fault[0]
    if kind == "stall":
      # respond normally, but only after the client's timeout has expired
      time.sleep(fault[1])
      return False
    if kind == "drop":
      # close the connection without sending anything (dropped keep-alive)
      self.close_connection = True
      return True
    if kind == "respond":
      code, payload = fault[1], fault[2]
      self._send_json(code, payload)
      return True
    raise ValueError(f"unknown fault kind: {kind}")

  # --- helpers --------------------------------------------------------------

  def _record(self):
    self.server.requests.append(
      (self.command, self.path,
       {k.lower(): v for k, v in self.headers.items()}))

  def _read_body(self):
    length = int(self.headers.get("Content-Length", 0))
    return self.rfile.read(length) if length else b""

  def _send_json(self, code, payload, extra_headers=None):
    body = json.dumps(payload).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    for k, v in (extra_headers or {}).items():
      self.send_header(k, v)
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def _send_bytes(self, code, body, content_length=None):
    self.send_response(code)
    self.send_header("Content-Type", "application/octet-stream")
    self.send_header("Content-Length",
                     str(len(body) if content_length is None else content_length))
    self.end_headers()
    self.wfile.write(body)

  # --- routes ---------------------------------------------------------------

  def do_POST(self):
    try:
      self._record()
      self._read_body()
      if self.path.endswith("/discover"):
        if self._apply_fault("discover"):
          return
        resp = self.server.discover_response
        if resp is None:
          resp = {"registered": True, "device_token": self.server.token}
        self._send_json(200, resp)
      elif self.path.endswith("/register"):
        if self._apply_fault("register"):
          return
        self._send_json(201, {"device_token": self.server.token,
                              "reused_existing": False})
      elif self.path.endswith("/status"):
        if self._apply_fault("status"):
          return
        self._send_json(200, {"status": 200, "next_poll_s": 30})
      elif self.path.endswith("/log"):
        if self._apply_fault("log"):
          return
        self._send_json(200, {})
      else:
        self._send_json(404, {"error": "not found"})
    except (BrokenPipeError, ConnectionResetError, OSError):
      # the client timed out / went away mid-response: expected in fault tests
      self.close_connection = True

  def do_GET(self):
    try:
      self._record()
      if self.path.endswith("/frame"):
        if self._apply_fault("frame"):
          return
        headers = {"ETag": self.server.etag,
                   "Content-Location": self.server.content_url}
        if self.headers.get("If-None-Match") == self.server.etag:
          self._send_json(304, {}, extra_headers=headers)
        else:
          self._send_json(200, {"url": self.server.content_url},
                          extra_headers=headers)
      elif "/content/" in self.path:
        if self._apply_fault("content"):
          return
        body = self.server.content
        override = self.server.content_length_override
        self._send_bytes(200, body, content_length=override)
        if override is not None:
          # advertised more than we sent: close so the client sees EOF
          self.close_connection = True
      else:
        self._send_json(404, {"error": "not found"})
    except (BrokenPipeError, ConnectionResetError, OSError):
      self.close_connection = True


class FakeTesseraeServer(ThreadingHTTPServer):
  """ scriptable fake Tesserae server bound to an ephemeral localhost port """

  def __init__(self):
    super().__init__(("127.0.0.1", 0), _Handler)
    self.token = "tok-shakedown-1"
    self.etag = "etag-v1"
    self.content = b"BM" + bytes(range(256)) * 8
    self.content_length_override = None
    self.discover_response = None      # None -> default "registered"
    self.faults = {}                   # endpoint-key -> [fault, ...]
    self.requests = []                 # (method, path, headers-dict)
    self._thread = None

  @property
  def url(self):
    return f"http://127.0.0.1:{self.server_address[1]}"

  @property
  def content_url(self):
    return f"{self.url}/content/dash.bin"

  def start(self):
    self._thread = threading.Thread(target=self.serve_forever, daemon=True)
    self._thread.start()

  def stop(self):
    self.shutdown()
    self.server_close()

  def push_fault(self, key, kind, *args):
    """ queue a fault for an endpoint key: discover|register|frame|status|content
    kinds: ("stall", seconds) | ("drop",) | ("respond", code, payload-dict) """
    self.faults.setdefault(key, []).append((kind, *args))

  def headers_for(self, path_part):
    """ recorded request headers for all requests matching path_part """
    return [h for m, p, h in self.requests if path_part in p]

  def count(self, path_part):
    return len(self.headers_for(path_part))
