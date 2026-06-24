"""Shared helpers for the hardware smoke-test scripts.

Hardware imports are lazy (inside functions) so the scripts byte-compile off-Pi.
"""

from __future__ import annotations


def open_gpiochip():
    """Open the 40-pin header gpiochip.

    On the Pi 5 (RP1) the header bank may be gpiochip0 or gpiochip4 depending on
    kernel, and BOTH open successfully — opening the wrong one drives unrelated
    lines. Set FREEDROID_GPIOCHIP=<n> to pin it; otherwise we try 0 then 4 and
    print which one we opened so the operator can correct it.
    """
    import os
    import sys

    import lgpio

    env = os.environ.get("FREEDROID_GPIOCHIP")
    candidates = [int(env)] if env else [0, 4]
    last_err = None
    for chip in candidates:
        try:
            handle = lgpio.gpiochip_open(chip)
        except Exception as e:  # lgpioError varies by version
            last_err = e
            continue
        hint = " (FREEDROID_GPIOCHIP)" if env else " — set FREEDROID_GPIOCHIP if pins don't respond"
        print(f"_hw: opened gpiochip{chip}{hint}", file=sys.stderr)
        return handle
    raise RuntimeError(f"could not open a gpiochip (tried {candidates}): {last_err}")
