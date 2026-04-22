# Run

Already set up: Python 3.12 venv at `.venv`, deps installed, `ng.pt` downloaded.

```powershell
# Terminal 1 — inference server (port 5555)
.venv\Scripts\python.exe scripts\serve.py ng.pt

# Terminal 2 — agent (needs the game running)
.venv\Scripts\python.exe scripts\play.py --process '<game>.exe'
```

Get `<game>.exe` from Task Manager → right-click process → Properties.

## Notes
- `flow_matching_transformer/nitrogen.py:186` patched for transformers 5.x (`SiglipVisionModel.vision_model` → fallback to `model`).
- GTX 1070: bfloat16 autocast emulated in fp32, ~0.54s/inference (18 actions per chunk).
- `play.py` requires a Windows game window; can't run headless.
