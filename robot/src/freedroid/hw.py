"""A gpiochip megnyitása — az EGYETLEN hely, ami tudja, melyik bankon ül a 40-pines fejléc.

Eddig ez a `scripts/_hw.py`-ban élt, mert csak a smoke-tesztek használták. A Phase 4-es
`motion/` és `safety/` ugyanezt a lapot nyitja, és két külön megnyitó-logika előbb-utóbb
szétcsúszik — a `scripts/_hw.py` most már innen re-exportál.
"""

from __future__ import annotations

import os
import sys


def open_gpiochip():
    """Megnyitja a 40-pines fejléc gpiochipjét, és visszaadja az lgpio handle-t.

    A Pi 5-ön (RP1) a fejléc bankja kerneltől függően `gpiochip0` vagy `gpiochip4`, és
    MINDKETTŐ sikeresen megnyílik — rossz lap megnyitása független lábakat vezérelne.
    A `FREEDROID_GPIOCHIP=<n>` rögzíti; egyébként 0-t próbálunk, aztán 4-et.

    MÉRVE 2026-08-13 ezen a gépen (`free-droid-001`, Debian 13, kernel 6.12.47): a
    `/dev/gpiochip4` SZIMLINK a `gpiochip0`-ra, tehát itt a próbálgatás nem tud rosszul
    választani. A környezeti változó egy MÁSIK image-hez marad meg biztonsági szelepnek.
    """
    import lgpio

    env = os.environ.get("FREEDROID_GPIOCHIP")
    candidates = [int(env)] if env else [0, 4]
    last_err = None
    for chip in candidates:
        try:
            handle = lgpio.gpiochip_open(chip)
        except Exception as e:  # lgpioError verziónként más
            last_err = e
            continue
        hint = " (FREEDROID_GPIOCHIP)" if env else " — set FREEDROID_GPIOCHIP if pins don't respond"
        print(f"_hw: opened gpiochip{chip}{hint}", file=sys.stderr)
        return handle
    raise RuntimeError(f"could not open a gpiochip (tried {candidates}): {last_err}")
