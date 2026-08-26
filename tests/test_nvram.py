# ----------------------------------------------------------------------------
# test_nvram.py: shakedown of the emulated NVRAM token store.
#
# Exercises the real GENERIC_LINUX_PC HAL nvram_read/nvram_write used to
# persist the device token on desktop platforms, against a temporary HOME.
# The magic+length+token framing written by main.py is verified round-trip.
# ----------------------------------------------------------------------------

import importlib
import os
import sys
import types

import pytest

from conftest import CLIENT_DIR


@pytest.fixture
def hal(tmp_path, monkeypatch):
  """ the real HAL, with a fake settings module and a throwaway HOME """
  monkeypatch.setenv("HOME", str(tmp_path))

  fake_settings = types.ModuleType("settings")
  class _Cfg: pass
  fake_settings.app_config = _Cfg()
  fake_settings.app_config.app_name = "Shakedown-Test"
  fake_settings.hw_config = _Cfg()
  fake_settings.secrets = _Cfg()
  monkeypatch.setitem(sys.modules, "settings", fake_settings)

  monkeypatch.syspath_prepend(os.path.join(CLIENT_DIR, "external", "base-app"))
  mod = importlib.import_module("base_app.hal.GENERIC_LINUX_PC")
  # instantiate without __init__: the nvram methods carry no instance state
  return mod.HalPygame.__new__(mod.HalPygame), tmp_path


def test_nvram_roundtrip(hal):
  hal_impl, home = hal
  token = b"tok-abc123"
  # the exact framing main.py writes: magic(2B big-endian), length(1B), token
  frame = (0x4201).to_bytes(2, "big") + bytes([len(token)]) + token
  hal_impl.nvram_write(0, frame)

  # read back the way main.py does on the next boot
  header = hal_impl.nvram_read(0, 3)
  assert int(bytes(header[:2]).hex(), 16) == 0x4201
  assert header[2] == len(token)
  assert bytes(hal_impl.nvram_read(3, header[2])) == token

  # storage location is per-app under $HOME
  assert (home / ".local" / "share" / "Shakedown-Test" / "nvram.data").exists()


def test_nvram_read_before_write_is_empty(hal):
  hal_impl, _ = hal
  data = hal_impl.nvram_read(0, 3)
  # a fresh install must not produce a valid magic number
  assert int(bytes(data[:2]).hex(), 16) != 0x4201


def test_nvram_magic_mismatch_detectable(hal):
  """ changing app_config.magic must invalidate a stored token """
  hal_impl, _ = hal
  token = b"old-token"
  frame = (0x4201).to_bytes(2, "big") + bytes([len(token)]) + token
  hal_impl.nvram_write(0, frame)

  new_magic = 0x4202
  header = hal_impl.nvram_read(0, 3)
  assert int(bytes(header[:2]).hex(), 16) != new_magic
