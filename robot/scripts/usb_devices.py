#!/usr/bin/env python3
"""Phase 1.5 smoke test — enumerate USB peripherals.

Runs lsusb, arecord -l, aplay -l and lists video devices so you can confirm the
webcam, USB mic and USB speaker are all present.
Run on the Pi:  uv run python scripts/usb_devices.py
"""

from __future__ import annotations

import glob
import shutil
import subprocess


def _run(cmd: list[str]) -> str:
    if shutil.which(cmd[0]) is None:
        return f"(missing: {cmd[0]})"
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (subprocess.SubprocessError, OSError) as e:
        return f"(error: {e})"


def main() -> int:
    print("== lsusb ==")
    print(_run(["lsusb"]))
    print("\n== arecord -l (capture / microphones) ==")
    print(_run(["arecord", "-l"]))
    print("\n== aplay -l (playback / speakers) ==")
    print(_run(["aplay", "-l"]))
    print("\n== video devices ==")
    print("\n".join(sorted(glob.glob("/dev/video*"))) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
