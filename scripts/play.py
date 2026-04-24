"""Live Overwatch play loop driven by a Gemma4VLA inference server.

Captures the OW window frame, asks scripts/serve.py for an action chunk, executes
the chunk frame-by-frame through Windows mouse/keyboard APIs, re-queries.
Windows-only (dxcam + pyautogui).
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if sys.platform != "win32":
    print("scripts/play.py is Windows-only", file=sys.stderr)
    sys.exit(2)

import dxcam
import pyautogui
import pywinctl as pwc
import zmq
from PIL import Image

from fpi.action_space import KEY_NAMES, decode_actions

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def find_overwatch_window():
    for w in pwc.getAllWindows():
        if (w.title or "").strip() == "Overwatch":
            return w
    raise RuntimeError("Overwatch window not found — start the game first")


class KeyState:
    """Tracks pressed keys/buttons so we only emit press/release on transitions."""

    def __init__(self):
        self.pressed: set[str] = set()

    def apply(self, raw_keys: dict[str, bool]) -> None:
        new = {k for k, v in raw_keys.items() if v}
        for k in new - self.pressed:
            self._press(k)
        for k in self.pressed - new:
            self._release(k)
        self.pressed = new

    def release_all(self) -> None:
        for k in list(self.pressed):
            self._release(k)
        self.pressed.clear()

    @staticmethod
    def _press(name: str) -> None:
        if name == "lmb":
            pyautogui.mouseDown(button="left")
        elif name == "rmb":
            pyautogui.mouseDown(button="right")
        else:
            pyautogui.keyDown(name)

    @staticmethod
    def _release(name: str) -> None:
        if name == "lmb":
            pyautogui.mouseUp(button="left")
        elif name == "rmb":
            pyautogui.mouseUp(button="right")
        else:
            pyautogui.keyUp(name)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="tcp://localhost:5556")
    p.add_argument("--instruction", default="play Overwatch")
    p.add_argument("--hz", type=float, default=30.0)
    args = p.parse_args()

    win = find_overwatch_window()
    cam = dxcam.create(output_color="RGB")
    cam.start(target_fps=int(args.hz),
              region=(win.left, win.top, win.right, win.bottom))

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(args.server)

    keys = KeyState()
    period = 1.0 / args.hz
    print(f"fpi play -> {args.server} @ {args.hz}Hz, instruction: {args.instruction!r}")
    try:
        while True:
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(period)
                continue
            sock.send(pickle.dumps({
                "type": "predict",
                "image": Image.fromarray(frame),
                "instruction": args.instruction,
            }))
            resp = pickle.loads(sock.recv())
            if resp.get("status") != "ok":
                print(f"server error: {resp}")
                continue
            chunk = resp["actions"][0]
            for raw in decode_actions(chunk):
                pyautogui.moveRel(int(raw.mouse_dx), int(raw.mouse_dy), _pause=False)
                keys.apply(raw.keys)
                time.sleep(period)
    except KeyboardInterrupt:
        print("stopping")
    finally:
        keys.release_all()
        cam.stop()
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
