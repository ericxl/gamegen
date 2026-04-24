"""Turn extracted per-player POVs + input tracks into training shards.

Upstream pipeline (in progress — see overwatch-training-data-pipeline.md and
overwatch_replay_finding.md): one replay code -> 10 per-player POVs on disk.

This script's input layout:
    pov_dir/
        <player_id>/
            frames/00000.png … NNNNN.png
            inputs.jsonl          one JSON object per frame:
                                  {"mouse_dx": ..., "mouse_dy": ..., "keys": {...}}

Output: one .npz per player containing (frames, actions, instructions) ready
for fpi.data.ReplayDataset.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from PIL import Image

from fpi.action_space import RawAction, encode_actions

CHUNK_LEN = 16  # must match Gemma4VLAConfig.chunk_len


def shard_player(player_dir: Path, instruction: str, out_path: Path) -> None:
    frame_paths = sorted((player_dir / "frames").glob("*.png"))
    inputs = [json.loads(line) for line in (player_dir / "inputs.jsonl").read_text().splitlines()]
    assert len(frame_paths) == len(inputs), f"frames/inputs length mismatch in {player_dir}"

    n_samples = len(frame_paths) - CHUNK_LEN
    if n_samples <= 0:
        print(f"[skip] {player_dir}: only {len(frame_paths)} frames, need >{CHUNK_LEN}")
        return

    frames = np.stack([np.array(Image.open(p)) for p in frame_paths[:n_samples]])
    actions = np.stack([
        encode_actions([
            RawAction(
                mouse_dx=inputs[i + k]["mouse_dx"],
                mouse_dy=inputs[i + k]["mouse_dy"],
                keys=inputs[i + k]["keys"],
            )
            for k in range(CHUNK_LEN)
        ])
        for i in range(n_samples)
    ]).astype(np.float32)
    instructions = np.array([instruction] * n_samples, dtype=object)

    np.savez_compressed(out_path, frames=frames, actions=actions, instructions=instructions)
    print(f"[save] {out_path}  ({n_samples} samples)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pov_dir", type=Path)
    p.add_argument("out_dir", type=Path)
    p.add_argument("--instruction", default="play Overwatch")
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for player_dir in sorted(args.pov_dir.iterdir()):
        if not player_dir.is_dir():
            continue
        shard_player(player_dir, args.instruction, args.out_dir / f"{player_dir.name}.npz")


if __name__ == "__main__":
    main()
