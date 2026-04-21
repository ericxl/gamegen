"""launch_ow_login.py — launch Overwatch directly; type creds if a login form appears.

OW.exe spawns Battle.net behind the scenes for authentication. If Battle.net
auto-logs-in (saved token valid), no form appears. If a login form does appear
(no token / token expired / Battle.net not yet running), this script types the
credentials baked in below.

Window mode is forced to "Windowed" by writing WindowMode = "2" in Settings_v0.ini
before launch.

Usage (from repo root):
    .venv\\Scripts\\python.exe scripts\\launch_ow_login.py
    .venv\\Scripts\\python.exe scripts\\launch_ow_login.py --kill-bnet  # force fresh state

Credentials: OW_EMAIL / OW_PASSWORD env vars override the embedded defaults.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import pyautogui
import pygetwindow as gw

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

EMAIL = os.environ.get("OW_EMAIL", "jkleitone@gmail.com")
PASSWORD = os.environ.get("OW_PASSWORD", "Welcomed56.")

OW_EXE = r"D:\Overwatch\_retail_\Overwatch.exe"
OW_SETTINGS = Path.home() / "Documents" / "Overwatch" / "Settings" / "Settings_v0.ini"
SHOT_DIR = Path(r"C:\depot\ow\captures\screenshots")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def shot(name: str) -> Path:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SHOT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    pyautogui.screenshot().save(p)
    print(f"[shot] {p}")
    return p


def kill_blizzard_processes() -> None:
    for image in ("Battle.net.exe", "Battle.net Launcher.exe", "Agent.exe",
                  "BlizzardError.exe", "Overwatch.exe"):
        subprocess.run(["taskkill", "/F", "/T", "/IM", image], capture_output=True)
    time.sleep(2)


def set_windowed_mode() -> None:
    """Set WindowMode = "2" (windowed) in Settings_v0.ini."""
    if not OW_SETTINGS.exists():
        print(f"[warn] settings file not found: {OW_SETTINGS}")
        return
    txt = OW_SETTINGS.read_text(encoding="utf-8-sig")
    new_txt, n = re.subn(
        r'^(WindowMode\s*=\s*")\d+(")',
        r'\g<1>2\g<2>',
        txt,
        flags=re.MULTILINE,
    )
    if n == 0:
        print("[warn] WindowMode key not found")
        return
    OW_SETTINGS.write_text(new_txt, encoding="utf-8-sig")
    print('[ok] WindowMode = "2" (windowed)')


def find_window(predicate, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in gw.getAllWindows():
            if w.visible and w.title and predicate(w):
                return w
        time.sleep(0.5)
    return None


def focus(w) -> None:
    """SetForegroundWindow has restrictions when called from a background app.
    Synthetic ALT + minimize/restore reliably defeats them."""
    try:
        if w.isMinimized:
            w.restore()
        user32.keybd_event(0x12, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(0x12, 0, 0x0002, 0)
        w.minimize()
        time.sleep(0.2)
        w.restore()
        time.sleep(0.2)
        try:
            w.activate()
        except Exception:
            pass
    except Exception as e:
        print(f"[warn] focus failed: {e}")
    time.sleep(0.8)


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def type_credentials() -> None:
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("delete")
    pyautogui.write(EMAIL, interval=0.03)
    time.sleep(0.3)
    pyautogui.press("tab")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("delete")
    pyautogui.write(PASSWORD, interval=0.03)
    time.sleep(0.3)
    pyautogui.press("enter")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kill-bnet", action="store_true",
                    help="Kill all Blizzard processes first (forces fresh state, may show login form)")
    args = ap.parse_args()

    if args.kill_bnet:
        print("[step] killing all Blizzard processes")
        kill_blizzard_processes()

    print("[step] forcing WindowMode = 2 (windowed)")
    set_windowed_mode()

    print(f"[step] launching {OW_EXE} -uid prometheus")
    subprocess.Popen([OW_EXE, "-uid", "prometheus"], cwd=str(Path(OW_EXE).parent))

    print("[step] sleeping 15s for OW to show login form")
    time.sleep(15)
    shot("01_pre_type")

    ow_w = next(
        (w for w in gw.getAllWindows()
         if w.visible and (w.title or "").strip() == "Overwatch"),
        None,
    )
    if not ow_w:
        print("[err] no Overwatch window found", file=sys.stderr)
        shot("err_no_ow_window")
        return 2

    print(f"[ok] Overwatch window: {ow_w.width}x{ow_w.height} @ ({ow_w.left},{ow_w.top})")
    focus(ow_w)
    time.sleep(0.8)

    fg = foreground_title()
    print(f"[check] foreground before typing: {fg!r}")
    if fg.strip() != "Overwatch":
        print("[abort] foreground is not Overwatch; refusing to type credentials",
              file=sys.stderr)
        shot("err_wrong_foreground")
        return 3

    print(f"[step] typing credentials for {EMAIL}")
    type_credentials()
    time.sleep(3.0)
    shot("02_post_submit")

    time.sleep(15)
    shot("03_final_state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
