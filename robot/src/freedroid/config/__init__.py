"""Central configuration — GPIO pinout and runtime tunables.

Build this first: every other module reads from here (per the spec).
"""

from freedroid.config import gpio
from freedroid.config.settings import Settings, load_settings

__all__ = ["gpio", "Settings", "load_settings"]
