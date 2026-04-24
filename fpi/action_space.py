"""Mouse + keyboard action space for Overwatch.

Layout (14-dim float vector per timestep, all values in [-1, 1]):
    0: mouse_dx       continuous, normalized by MOUSE_SCALE
    1: mouse_dy       continuous, normalized by MOUSE_SCALE
    2..13: 12 binary controls, encoded as -1 (released) / +1 (pressed)

The 12 binary slots match the keys an Overwatch player actually uses end-to-end.
Keeping all 14 channels float-valued lets a single flow-matching head produce
the whole action; binary controls are thresholded at 0 at decode time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ACTION_DIM = 14

KEY_NAMES: tuple[str, ...] = (
    "w",
    "a",
    "s",
    "d",
    "space",
    "shift",
    "ctrl",
    "e",
    "q",
    "r",
    "lmb",
    "rmb",
)
assert len(KEY_NAMES) == ACTION_DIM - 2

MOUSE_SCALE = 600.0


@dataclass
class RawAction:
    """Raw per-frame input as captured from a player's POV."""
    mouse_dx: float
    mouse_dy: float
    keys: dict[str, bool]


def encode_actions(raws: list[RawAction]) -> np.ndarray:
    """Pack a chunk of raw inputs into a (T, ACTION_DIM) float32 array in [-1, 1]."""
    out = np.zeros((len(raws), ACTION_DIM), dtype=np.float32)
    for t, a in enumerate(raws):
        out[t, 0] = np.clip(a.mouse_dx / MOUSE_SCALE, -1.0, 1.0)
        out[t, 1] = np.clip(a.mouse_dy / MOUSE_SCALE, -1.0, 1.0)
        for i, k in enumerate(KEY_NAMES):
            out[t, 2 + i] = 1.0 if a.keys.get(k, False) else -1.0
    return out


def decode_actions(arr: np.ndarray) -> list[RawAction]:
    """Inverse of encode_actions. arr is (T, ACTION_DIM) float in [-1, 1]."""
    assert arr.ndim == 2 and arr.shape[1] == ACTION_DIM
    out: list[RawAction] = []
    for t in range(arr.shape[0]):
        keys = {k: bool(arr[t, 2 + i] > 0.0) for i, k in enumerate(KEY_NAMES)}
        out.append(RawAction(
            mouse_dx=float(arr[t, 0]) * MOUSE_SCALE,
            mouse_dy=float(arr[t, 1]) * MOUSE_SCALE,
            keys=keys,
        ))
    return out
