"""Capture synchronized OW frames + mouse/keyboard inputs from a human playing live.

Stopgap for the unsolved replay-extraction path (see overwatch_replay_finding.md).
The user plays Overwatch normally; this script logs the OW window + their inputs
in the layout scripts/build_dataset.py expects:

    out_dir/<session_id>/
        frames/00000.png … NNNNN.png
        inputs.jsonl           one JSON line per frame:
            {"mouse_dx": float, "mouse_dy": float, "keys": {"w": bool, ...}}

Run OW in Windowed/Borderless mode (launch_ow_login.py already enforces this) —
pynput hooks unreliably under exclusive fullscreen.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if sys.platform != "win32":
    print("scripts/capture_live.py is Windows-only", file=sys.stderr)
    sys.exit(2)

import dxcam
import pywinctl as pwc
from PIL import Image
from pynput import keyboard, mouse

from fpi.action_space import KEY_NAMES


def find_overwatch_window():
    for w in pwc.getAllWindows():
        if (w.title or "").strip() == "Overwatch":
            return w
    raise RuntimeError("Overwatch window not found — start the game first")


def _normalize_key(k) -> str | None:
    """Map a pynput key/button to one of KEY_NAMES, or None if unmapped."""
    if isinstance(k, mouse.Button):
        if k == mouse.Button.left:
            return "lmb"
        if k == mouse.Button.right:
            return "rmb"
        return None
    if isinstance(k, keyboard.Key):
        if k == keyboard.Key.space:
            return "space"
        if k in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            return "shift"
        if k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return "ctrl"
        return None
    if isinstance(k, keyboard.KeyCode) and k.char:
        c = k.char.lower()
        if c in KEY_NAMES:
            return c
    return None


class InputAccumulator:
    """Shared state written by pynput listener threads, drained each frame."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.dx = 0.0
        self.dy = 0.0
        self._last_xy: tuple[int, int] | None = None
        self.pressed: set[str] = set()

    def on_move(self, x, y) -> None:
        # Absolute position; convert to delta against last seen position.
        with self._lock:
            if self._last_xy is None:
                self._last_xy = (x, y)
                return
            lx, ly = self._last_xy
            self.dx += x - lx
            self.dy += y - ly
            self._last_xy = (x, y)

    def on_click(self, x, y, button, is_pressed) -> None:
        name = _normalize_key(button)
        if name is None:
            return
        with self._lock:
            if is_pressed:
                self.pressed.add(name)
            else:
                self.pressed.discard(name)

    def on_press(self, key) -> None:
        name = _normalize_key(key)
        if name is None:
            return
        with self._lock:
            self.pressed.add(name)

    def on_release(self, key) -> None:
        name = _normalize_key(key)
        if name is None:
            return
        with self._lock:
            self.pressed.discard(name)

    def snapshot(self) -> tuple[float, float, dict[str, bool]]:
        """Return cumulative (dx, dy, keys-snapshot) and reset deltas."""
        with self._lock:
            dx, dy = self.dx, self.dy
            self.dx = 0.0
            self.dy = 0.0
            keys = {k: (k in self.pressed) for k in KEY_NAMES}
        return dx, dy, keys


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--session-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    p.add_argument("--hz", type=float, default=30.0)
    args = p.parse_args()

    session_dir = args.out_dir / args.session_id
    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    inputs_path = session_dir / "inputs.jsonl"

    win = find_overwatch_window()
    print(f"[ok] Overwatch window: {win.width}x{win.height} @ ({win.left},{win.top})")

    cam = dxcam.create(output_color="RGB")
    cam.start(target_fps=int(args.hz),
              region=(win.left, win.top, win.right, win.bottom))

    acc = InputAccumulator()
    kb_listener = keyboard.Listener(on_press=acc.on_press, on_release=acc.on_release)
    mouse_listener = mouse.Listener(on_move=acc.on_move, on_click=acc.on_click)
    kb_listener.start()
    mouse_listener.start()

    period = 1.0 / args.hz
    inputs_f = inputs_path.open("a", encoding="utf-8")
    n = 0
    t0 = time.time()
    last_log_t = t0
    last_log_n = 0
    print(f"capturing -> {session_dir} @ {args.hz}Hz (Ctrl-C to stop)")
    try:
        while True:
            tick_start = time.time()
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(period)
                continue

            dx, dy, keys = acc.snapshot()
            Image.fromarray(frame).save(frames_dir / f"{n:05d}.png")
            line = json.dumps({"mouse_dx": float(dx), "mouse_dy": float(dy), "keys": keys})
            inputs_f.write(line + "\n")
            inputs_f.flush()
            os.fsync(inputs_f.fileno())
            n += 1

            if n % 30 == 0:
                now = time.time()
                hz = (n - last_log_n) / max(now - last_log_t, 1e-6)
                print(f"[{n:5d}] recent {hz:.1f} Hz")
                last_log_t = now
                last_log_n = n

            elapsed = time.time() - tick_start
            if elapsed < period:
                time.sleep(period - elapsed)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        kb_listener.stop()
        mouse_listener.stop()
        cam.stop()
        inputs_f.close()
        dur = time.time() - t0
        avg_hz = n / dur if dur > 0 else 0.0
        print(f"[done] {n} frames in {dur:.1f}s = {avg_hz:.1f} Hz -> {session_dir}")


if __name__ == "__main__":
    main()
