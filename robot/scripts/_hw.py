"""Shared helpers for the hardware smoke-test scripts.

Hardware imports are lazy (inside functions) so the scripts byte-compile off-Pi.
"""

from __future__ import annotations


def open_gpiochip():
    """Open the 40-pin header gpiochip. On the Pi 5 (RP1) it may be 0 or 4."""
    import lgpio

    last_err = None
    for chip in (0, 4):
        try:
            return lgpio.gpiochip_open(chip)
        except Exception as e:  # lgpioError varies by version
            last_err = e
    raise RuntimeError(f"could not open a gpiochip (tried 0, 4): {last_err}")
