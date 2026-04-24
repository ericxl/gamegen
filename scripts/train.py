"""Behavior-cloning training of Gemma4VLA on Overwatch replay shards.

Loads the Gemma 4 VL backbone + flow-matching action expert, runs flow-matching
MSE loss against extracted (frame, instruction, action_chunk) tuples from
.npz shards produced by scripts/build_dataset.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import torch
from torch.utils.data import DataLoader
from transformers import AutoProcessor

from fpi.data import ReplayDataset, make_collate
from fpi.model import Gemma4VLA, Gemma4VLAConfig


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--shards", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, default=Path("checkpoints/fpi"))
    p.add_argument("--model-id", default="google/gemma-4-E4B-it")
    p.add_argument("--kv-dim", type=int, default=2560)
    p.add_argument("--chunk-len", type=int, default=16)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--steps", type=int, default=20000)
    p.add_argument("--save-every", type=int, default=2000)
    p.add_argument("--freeze-backbone", action="store_true")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cfg = Gemma4VLAConfig(
        backbone_model_id=args.model_id,
        kv_dim=args.kv_dim,
        chunk_len=args.chunk_len,
    )
    model = Gemma4VLA(cfg).to("cuda")
    processor = AutoProcessor.from_pretrained(args.model_id)

    if args.freeze_backbone:
        for param in model.backbone.parameters():
            param.requires_grad_(False)

    trainable = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable, lr=args.lr)

    ds = ReplayDataset(args.shards)
    loader = DataLoader(
        ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=2,
        collate_fn=make_collate(processor),
    )

    step = 0
    while step < args.steps:
        for backbone_inputs, actions in loader:
            backbone_inputs = {
                k: (v.to("cuda") if hasattr(v, "to") else v)
                for k, v in backbone_inputs.items()
            }
            actions = actions.to("cuda")
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                loss = model.flow_matching_loss(actions, backbone_inputs)
            opt.zero_grad()
            loss.backward()
            opt.step()
            if step % 50 == 0:
                print(f"step {step:6d}  loss={loss.item():.4f}")
            if step > 0 and step % args.save_every == 0:
                ckpt_path = args.out / f"ckpt_{step:06d}.pt"
                torch.save({"model": model.state_dict(), "cfg": cfg.__dict__}, ckpt_path)
                print(f"[save] {ckpt_path}")
            step += 1
            if step >= args.steps:
                break

    final = args.out / "ckpt_final.pt"
    torch.save({"model": model.state_dict(), "cfg": cfg.__dict__}, final)
    print(f"[done] {final}")


if __name__ == "__main__":
    main()
