#!/usr/bin/env python3
"""Phase 1.5 helper — A/B the microphones (webcam vs USB omni) and pick one.

Records a short sample from every ALSA capture card so you can listen back and
keep the clearer one, then prints how to make it the default / disable the other.
Run on the Pi:  uv run python scripts/mic_select.py [--seconds 4]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

OUT_DIR = Path("/tmp/freedroid-mic")


def _capture_cards() -> list[tuple[str, str]]:
    """(card_number, description) for each ALSA capture device."""
    if shutil.which("arecord") is None:
        return []
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    cards = []
    for m in re.finditer(r"card (\d+): (\S+).*?\[(.*?)\]", out):
        cards.append((m.group(1), m.group(3)))
    return cards


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=4)
    args = ap.parse_args()

    cards = _capture_cards()
    if not cards:
        print("No ALSA capture devices found (is arecord installed, mics plugged in?)")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Found {len(cards)} capture device(s). Recording {args.seconds}s from each:\n")
    for card, desc in cards:
        wav = OUT_DIR / f"card{card}.wav"
        print(f"  card {card} [{desc}] -> {wav}  (speak now)")
        subprocess.run(
            ["arecord", "-D", f"plughw:{card},0", "-d", str(args.seconds),
             "-f", "S16_LE", "-r", "16000", "-c", "1", str(wav)],
            capture_output=True, text=True,
        )

    print("\nListen back with:  aplay /tmp/freedroid-mic/card<N>.wav")
    print("Keep the clearer one. To make card N the default capture device, create")
    print("~/.asoundrc (or /etc/asound.conf):\n")
    print('  pcm.!default { type asym capture.pcm "mic" }')
    print('  pcm.mic { type plug slave.pcm "plughw:N,0" }\n')
    print("The other mic is then simply unused; no need to physically disable it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
