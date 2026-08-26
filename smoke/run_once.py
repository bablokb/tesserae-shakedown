#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# run_once.py: run ONE Tesserae client cycle headless and record the outcome.
#
# Must be run with the CLIENT's venv python:
#   TESSERAE_DISPLAY=<type> .../venv.tesserae.cp-client/bin/python3 \
#       run_once.py <output-dir> <client-src-dir>
#
# Drives the real client (main.py) end-to-end against the real server, with:
#   - SDL dummy video driver, so no window is needed (override with
#     SHAKEDOWN_WINDOWED=1 to watch it live)
#   - app_config.always_on forced off, so exactly one cycle runs
#   - UIApplication.shutdown patched to classify the outcome and save the
#     rendered framebuffer as PNG instead of blocking on the pygame window
#
# Writes <output-dir>/<display>.json with outcome OK | PENDING | FAIL and,
# when a dashboard was painted, <output-dir>/<display>.png.
# ----------------------------------------------------------------------------

import json
import os
import runpy
import signal
import sys


def main():
  out_dir = os.path.abspath(sys.argv[1])
  client_src = os.path.abspath(sys.argv[2])
  disp = os.environ.get("TESSERAE_DISPLAY", "native")
  os.makedirs(out_dir, exist_ok=True)

  if not os.environ.get("SHAKEDOWN_WINDOWED"):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
  os.environ.setdefault("BLINKA_FORCEBOARD", "GENERIC_LINUX_PC")
  os.environ.setdefault("BLINKA_FORCECHIP", "GENERIC_X86")

  # hard stop: a hung cycle must not stall the whole shakedown
  signal.alarm(int(os.environ.get("SHAKEDOWN_CYCLE_TIMEOUT", "90")))

  os.chdir(client_src)
  sys.path.insert(0, client_src)

  outcome = {"display": disp, "outcome": "FAIL",
             "detail": "client did not reach shutdown"}
  out_json = os.path.join(out_dir, f"{disp}.json")

  def write_outcome():
    with open(out_json, "w") as f:
      json.dump(outcome, f, indent=2)

  write_outcome()   # written up-front so a hard crash still leaves a record

  import settings
  settings.app_config.always_on = False   # exactly one cycle, then shutdown
  settings.app_config.debug = True

  from base_app.ui_application import UIApplication

  def shakedown_shutdown(self, with_wakeup=True):
    painted = bool(self.data.get("dashboard"))
    registered = bool(self.data.get("token"))
    if not with_wakeup:
      outcome.update(outcome="FAIL",
                     detail="cycle raised an exception (see log)")
    elif painted:
      outcome.update(outcome="OK", detail="registered, dashboard fetched and painted")
    elif not registered:
      outcome.update(outcome="PENDING",
                     detail="device unknown to server - awaiting admin approval")
    else:
      outcome.update(outcome="OK",
                     detail="cycle ok (no repaint: frame unchanged, 304)")
    try:
      import pygame
      surface = pygame.display.get_surface()
      if surface and painted:
        # this pygame build cannot encode PNG (no SDL_image saving), so
        # save BMP and convert with sips where available (macOS)
        bmp = os.path.join(out_dir, f"{disp}.bmp")
        plain = pygame.Surface(surface.get_size(), 0, 24)
        plain.blit(surface, (0, 0))
        pygame.image.save(plain, bmp)
        outcome["png"] = bmp
        import subprocess
        png = os.path.join(out_dir, f"{disp}.png")
        rc = subprocess.run(["sips", "-s", "format", "png", bmp, "--out", png],
                            capture_output=True).returncode
        if rc == 0:
          os.remove(bmp)
          outcome["png"] = png
    except Exception as ex:
      outcome["png_error"] = repr(ex)
    write_outcome()
    return None   # instead of blocking on the pygame window

  UIApplication.shutdown = shakedown_shutdown

  try:
    runpy.run_path(os.path.join(client_src, "main.py"), run_name="__main__")
  except SystemExit:
    pass
  except Exception as ex:
    outcome.update(outcome="FAIL", detail=f"unhandled exception: {ex!r}")
    write_outcome()
    raise
  finally:
    signal.alarm(0)

  sys.exit(0 if outcome["outcome"] in ("OK", "PENDING") else 1)


if __name__ == "__main__":
  main()
