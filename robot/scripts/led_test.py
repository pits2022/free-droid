#!/usr/bin/env python3
"""A gyűrű bring-up próbája: minden spec §6 jelenet 3 másodpercig. Pi-n, rádugva:

    cd robot && uv run python scripts/led_test.py [--count 12] [--brightness 0.3]
"""
from __future__ import annotations

import argparse
import time

from freedroid import led

JELENETEK = [
    ("boot OK", led.BOOT_OK),
    ("vár", led.Scene(led.Pattern.BREATHE, led.WHITE)),
    ("vár, gyenge akku", led.Scene(led.Pattern.BREATHE, led.ORANGE)),
    ("FIGYEL", led.Scene(led.Pattern.PULSE, led.GREEN)),
    ("gondolkodik – FELHŐ", led.Scene(led.Pattern.SPIN, led.BLUE)),
    ("gondolkodik – EDGE", led.Scene(led.Pattern.SPIN, led.PURPLE)),
    ("beszél – edge", led.Scene(led.Pattern.SOLID, led.PURPLE)),
    ("mozog előre", led.Scene(led.Pattern.CHASE, led.WHITE)),
    ("mozog hátra", led.Scene(led.Pattern.CHASE, led.WHITE, direction=-1)),
    ("akadály", led.OBSTACLE),
    ("SAFE", led.SAFE),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--brightness", type=float, default=0.3)
    a = p.parse_args()
    aktualis = [led.OFF]
    ctl = led.LedController(led.build_ring(a.count, a.brightness), lambda: aktualis[0], a.count)
    ctl.start()
    try:
        for nev, jelenet in JELENETEK:
            print(nev, flush=True)
            aktualis[0] = jelenet
            time.sleep(3)
    finally:
        ctl.close()


if __name__ == "__main__":
    main()
