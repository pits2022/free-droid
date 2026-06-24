"""Vital-function health checks for the droid (network / hardware / software).

Runs at boot and on a timer via systemd (`freedroid-health`). On a vital failure it
self-heals (restart the relevant service) and, if that fails, enters safe-mode.
"""

from freedroid.health.model import (
    CheckResult,
    HealthReport,
    Layer,
    Severity,
    Status,
)
from freedroid.health.runner import build_report, heal_and_recheck, run_checks

__all__ = [
    "CheckResult",
    "HealthReport",
    "Layer",
    "Severity",
    "Status",
    "build_report",
    "heal_and_recheck",
    "run_checks",
]
