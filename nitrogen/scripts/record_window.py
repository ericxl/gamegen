"""Record a Windows window region to mp4 until a sentinel file appears.

Usage: record_window.py <window_title> <output_mp4> <sentinel_path> [fps]

The sentinel-file stop mechanism is used so the mp4 is finalized cleanly
(moov atom written) — killing the process mid-write would leave a broken file.
"""
import sys
import os
import time

import dxcam
import pywinctl as pwc
import av


def main():
    window_title = sys.argv[1]
    output_path = sys.argv[2]
    sentinel_path = sys.argv[3]
    fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    windows = pwc.getAllWindows()
    win = next((w for w in windows if w.title == window_title), None)
    if win is None:
        print(f"Window '{window_title}' not found", flush=True)
        sys.exit(1)
    l, t, r, b = win.left, win.top, win.right, win.bottom
    width, height = r - l, b - t
    # h264 yuv420p needs even dims
    if width % 2:
        width -= 1
    if height % 2:
        height -= 1
    print(f"Window region: ({l},{t},{l+width},{t+height}) size {width}x{height}", flush=True)

    camera = dxcam.create(output_color="BGR")

    container = av.open(output_path, mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "23", "preset": "veryfast"}

    print(f"Recording -> {output_path} at {width}x{height}@{fps}fps", flush=True)
    print(f"Stop by creating: {sentinel_path}", flush=True)

    n = 0
    last_frame = None
    next_t = time.perf_counter()
    interval = 1.0 / fps
    last_print = time.time()
    try:
        while not os.path.exists(sentinel_path):
            frame = camera.grab(region=(l, t, l + width, t + height))
            if frame is not None:
                last_frame = frame
            if last_frame is not None:
                avframe = av.VideoFrame.from_ndarray(last_frame, format="bgr24")
                for packet in stream.encode(avframe):
                    container.mux(packet)
                n += 1
            next_t += interval
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                # Falling behind, reset clock
                next_t = time.perf_counter()
            if time.time() - last_print > 5:
                print(f"  ... {n} frames", flush=True)
                last_print = time.time()
    finally:
        for packet in stream.encode(None):
            container.mux(packet)
        container.close()
        print(f"DONE. {n} frames -> {output_path}", flush=True)


if __name__ == "__main__":
    main()
