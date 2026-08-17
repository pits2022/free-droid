"""Shared helpers for the hardware smoke-test scripts.

A `open_gpiochip` átköltözött a csomagba (`freedroid.hw`), mert a Phase 4-es `motion/`
és `safety/` is ugyanazt a lapot nyitja. Ez a modul megmarad, hogy a scriptek `import
_hw` sora ne változzon.
"""

from __future__ import annotations

from freedroid.hw import open_gpiochip

__all__ = ["open_gpiochip"]
