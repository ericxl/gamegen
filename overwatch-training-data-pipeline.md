# Project: Overwatch VLA training data pipeline

## North star
Train a Vision-Language-Action model that plays Overwatch.

## Goal
Collect training data. The richest source is **full match replays** — not highlights, not user-exported MP4s.

**Input:** one Overwatch replay code (test code: `7Q7AG2`).
**Output:** one POV per player in the match (no spectators), each paired with a per-frame **keyboard and mouse** track.

Our pipeline should be as fast as possible. At the minimum, we could accomplish the goal, by simulating clicks, etc and record the videos of overwatch actually opening the code, switching POV. But this is too long (say one game 10 players, this would take 1hour per match!)
Therefore our goal, is to actually figure out a programmatic way as much as possible.

## References
1. **Source codes**: scrape [owreplays.tv](https://owreplays.tv) for replay codes.

## Critical constraints
- **Replays are server-side reenactments.** There is no documented on-disk replay file — the client receives data from Blizzard and re-simulates locally. The first goal is to intercept that received data; treat "no replay file" as a target to break, not an immutable fact.
- **Codes invalidate on every patch.** Scraping and capture have to keep up with the patch cadence, or we lose the backlog. This is what makes the eventual fast-export goal load-bearing, not just nice-to-have.


## Related work in repo
- `overwatch_memory_reading.md` — notes on reading game state from process memory. Directly relevant to the first goal: memory-reading the client after replay data is received may be the cheapest path to the raw stream.
