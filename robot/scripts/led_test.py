#!/usr/bin/env python3
"""A gyűrű bring-up próbája: minden spec §6 jelenet 3 másodpercig. Pi-n, rádugva:

    sudo systemctl stop freedroid     # az orchestrator is hajtja a gyűrűt — egy SPI, egy író
    cd robot && uv run python scripts/led_test.py [--count 24] [--brightness 0.3]

A LED-szám és a fényerő alapból a `LedSettings`-ből jön (env-felülírással is:
`FREEDROID_LED_COUNT`), nem beégetett számból — 2026-09-07-ig itt egy MÁSOLAT állt,
ami a config 12-es tippjével együtt öregedett, és a 24-es gyűrűnek a felét hajtotta.
"""
from __future__ import annotations

import argparse
import time

from freedroid import led
from freedroid.config.settings import load_settings

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
    cfg = load_settings().led
    p.add_argument("--count", type=int, default=cfg.count)
    p.add_argument("--brightness", type=float, default=cfg.brightness)
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
