"""Replay dataset interface.

Shard format (one .npz per shard):
    frames:       (N, H, W, 3) uint8     — single POV frame per sample
    actions:      (N, T, ACTION_DIM) f32  — encoded by fpi.action_space.encode_actions
    instructions: (N,) object             — UTF-8 strings, one per sample

build_dataset.py populates these from per-player POV videos + input tracks.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from fpi.action_space import ACTION_DIM


class ReplayDataset(Dataset):
    def __init__(self, shard_paths: list[Path]):
        self.shards = [np.load(p, allow_pickle=True) for p in shard_paths]
        self.index: list[tuple[int, int]] = []
        for si, shard in enumerate(self.shards):
            for li in range(len(shard["actions"])):
                self.index.append((si, li))

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int) -> dict:
        si, li = self.index[i]
        shard = self.shards[si]
        return {
            "frame": shard["frames"][li],
            "instruction": str(shard["instructions"][li]),
            "action": shard["actions"][li].astype(np.float32),
        }


def make_collate(processor):
    """Returns a collate_fn that runs the Gemma 4 processor over a batch."""
    def collate(batch: list[dict]) -> tuple[dict, torch.Tensor]:
        frames = [item["frame"] for item in batch]
        instructions = [item["instruction"] for item in batch]
        actions = torch.from_numpy(np.stack([item["action"] for item in batch]))
        backbone_inputs = processor(
            images=frames,
            text=instructions,
            return_tensors="pt",
            padding=True,
        )
        return dict(backbone_inputs), actions
    return collate
