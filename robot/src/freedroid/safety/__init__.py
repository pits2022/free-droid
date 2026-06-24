"""Safety watchdog — the "reflex" layer.

Reads the HC-SR04P ultrasonic sensors on a SEPARATE thread and calls motion.stop()
the instant any sensor reads below threshold — without ever consulting the LLM.
Interface + stub only.
"""

from __future__ import annotations

from typing import Callable, Protocol


class Watchdog(Protocol):
    def start(self) -> None: ...
    def stop_monitoring(self) -> None: ...
    def distances_cm(self) -> dict[str, float]: ...
    def is_blocked(self) -> bool: ...


class UltrasonicWatchdog:
    """Threaded HC-SR04P watchdog (Pi-only, lgpio). STUB.

    on_obstacle is invoked (e.g. motion.stop) when any reading drops below threshold.
    """

    def __init__(self, on_obstacle: Callable[[], None], settings=None) -> None:
        raise NotImplementedError("Phase 4.1: implement threaded ultrasonic watchdog")

    def start(self) -> None:
        raise NotImplementedError

    def stop_monitoring(self) -> None:
        raise NotImplementedError

    def distances_cm(self) -> dict[str, float]:
        raise NotImplementedError

    def is_blocked(self) -> bool:
        raise NotImplementedError
