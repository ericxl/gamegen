"""ZMQ inference server for a trained Gemma4VLA checkpoint.

Wire protocol (pickle over ZMQ REP/REQ):
    {"type": "predict", "image": PIL.Image, "instruction": str}
        -> {"status": "ok", "actions": ndarray (1, T, ACTION_DIM)}
    {"type": "info"}
        -> {"status": "ok", "cfg": dict}

Default port is 5556 (NitroGen's reference server uses 5555).
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import torch
import zmq
from transformers import AutoProcessor

from fpi.model import Gemma4VLA, Gemma4VLAConfig


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("ckpt", type=Path)
    p.add_argument("--port", type=int, default=5556)
    args = p.parse_args()

    blob = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    cfg = Gemma4VLAConfig(**blob["cfg"])
    model = Gemma4VLA(cfg).to("cuda").eval()
    model.load_state_dict(blob["model"])
    processor = AutoProcessor.from_pretrained(cfg.backbone_model_id)

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(f"tcp://*:{args.port}")
    print(f"fpi serve on tcp://*:{args.port}")

    try:
        while True:
            req = pickle.loads(sock.recv())
            if req["type"] == "predict":
                inputs = processor(
                    images=[req["image"]],
                    text=[req.get("instruction", "")],
                    return_tensors="pt",
                    padding=True,
                )
                inputs = {
                    k: (v.to("cuda") if hasattr(v, "to") else v) for k, v in inputs.items()
                }
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    actions = model.sample_actions(inputs)
                sock.send(pickle.dumps({"status": "ok", "actions": actions.cpu().numpy()}))
            elif req["type"] == "info":
                sock.send(pickle.dumps({"status": "ok", "cfg": cfg.__dict__}))
            else:
                sock.send(pickle.dumps({"status": "error", "msg": f"unknown type: {req['type']}"}))
    except KeyboardInterrupt:
        print("shutting down")
    finally:
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
