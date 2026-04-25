# gamegen: foundation model for fastpaced generalist gaming agents

## Why this exists

The long-term goal is a generalist robotic model that can think *and* take continuous, fast-paced action. Today's architectures don't support that. LLMs reason but don't act in real time. VLAs act but don't reason deeply. We want both at once.

Games are a good training ground for this. But the game has to be the right kind. Turn-based games are already in LLM territory, so they don't push the architecture forward. We need something **multiplayer and fast-paced**, where thinking and acting happen at the same time.

## Why Overwatch

Overwatch isn't just a shooter. It has many heroes, each with their own playstyle, abilities, and decision space. Training across all of them forces a model toward general intelligence rather than a single narrow skill.

## Why Overwatch replays

Overwatch replays restore the full match from any of the 10 players' perspectives. A single replay code is enough to reconstruct every player's POV with their exact inputs — the ones they actually made, not estimates. So one ~10-minute match yields ~100 minutes of high-quality, accurately annotated POV video, all from one code.

## Approach: NitroGen + Gemma 4

Two open-weight pieces, glued together.

- **[NitroGen](https://nitrogen.minedojo.org)** (NVIDIA, Dec 2025) — a vision-action foundation model trained on 40k hours of public gameplay. Pixels in, controller out, action-chunked via flow matching. Fast system-1 reaction. No language conditioning.
- **[Gemma 4](https://deepmind.google/models/gemma/gemma-4/)** (Google DeepMind, Apr 2026) — open multimodal VLM, native vision + language, Apache 2.0. Reasoning and language conditioning, at LLM latency.

We take NitroGen's recipe (flow-matching action expert, action chunking, behavior cloning on frame→action pairs) and rebuild it with Gemma 4 as the backbone. The action space is keyboard + mouse, not gamepad, because Overwatch is M+KB.

```
[POV frame] + [language goal / sub-task]
                    │
                    ▼  Gemma 4 (vision-language backbone)
                    │  last hidden states as cross-attention KV
                    ▼
       Flow-matching action expert (~50–300M params)
                    │
                    ▼
   [chunk of next ~0.5 s of mouse + key inputs]
```

Why the combination:
- NitroGen alone is system-1 only — no instruction-following, no reasoning over UI, comms, or hero state.
- Gemma 4 alone runs at LLM latency — too slow for 30–60 Hz control.
- Action chunking lets Gemma fire at 2–5 Hz while the action expert plays smoothly between queries.

This mirrors the architectural shift in robotics from RT-2 (autoregressive action tokens) to π0 (continuous flow-matching action expert) to π0.7 (richer multimodal conditioning + hierarchy). We're transplanting the same shift back into games.

## Code

```
fpi/
  action_space.py        14-dim mouse + keyboard action vector + encode/decode
  model.py               Gemma4VLA: backbone + flow-matching action expert
  data.py                ReplayDataset over .npz shards

scripts/
  capture_live.py        live human-teleop capture: frames + M+KB inputs (Windows)
  build_dataset.py       per-player POVs + input tracks -> training shards
  train.py               behavior-cloning loop (flow-matching MSE)
  serve.py               ZMQ inference server
  play.py                live Overwatch play loop (Windows, M+KB dispatch)

nitrogen/                vendored NitroGen reference implementation
```

The `nitrogen/` subtree is the unmodified NitroGen reference, kept as a comparison baseline and as a fallback agent — see [`nitrogen/RUN.md`](nitrogen/RUN.md).

## Pipeline (in progress)

Two halves.

**Data.** Two paths to labeled (frame, input) pairs:

- *Fast (unsolved):* Replay code → 10 per-player POVs reconstructed from the network stream. See [`overwatch-training-data-pipeline.md`](overwatch-training-data-pipeline.md), [`overwatch_replay_finding.md`](overwatch_replay_finding.md), [`overwatch_memory_reading.md`](overwatch_memory_reading.md).
- *Slow (working):* `scripts/capture_live.py` records a human playing live — synchronized OW window frames + actual M+KB inputs at 30Hz, in the layout `scripts/build_dataset.py` consumes. Useful as a stopgap and as a sanity-test corpus for the training loop.

**Model.** Gemma 4 + flow-matching action expert, behavior-cloned on the data above. Scaffold lives in `fpi/` and `scripts/`.

```bash
pip install -e .[play]                       # install fpi + Windows play deps
python scripts/capture_live.py --out-dir captures/  # collect human demos
python scripts/build_dataset.py captures/ shards/   # turn into training shards
python scripts/train.py --shards shards/*.npz       # BC training
python scripts/serve.py checkpoints/fpi/ckpt_final.pt  # inference server
python scripts/play.py                              # live agent against OW
```

![demo](demo2.gif)

The clip above is the current state of the data extraction pipeline, not the trained agent.
