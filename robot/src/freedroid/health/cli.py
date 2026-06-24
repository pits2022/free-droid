"""`freedroid-health` entry point.

Run at boot and on a timer (systemd). Flow: run checks → self-heal fixable
failures → re-check → write a JSON status file + log to journald → set safe-mode
(or clear it) → exit 0 if vital functions are healthy, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
import time

from freedroid.config.settings import load_settings
from freedroid.health.model import HealthReport, Status
from freedroid.health.runner import heal_and_recheck
from freedroid.health.safemode import clear_safe_mode, enter_safe_mode

STATUS_PATH = os.environ.get("FREEDROID_HEALTH_STATUS", "/run/freedroid/health.json")


def write_status(report: HealthReport, path: str | None = None) -> None:
    path = path or STATUS_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(report.to_json())
    except OSError as e:  # pragma: no cover - defensive
        print(f"health: cannot write status {path}: {e}", file=sys.stderr)


def log_report(report: HealthReport) -> None:
    print(f"health: {report.summary()}", file=sys.stderr)
    for r in report.results:
        if r.status is not Status.OK:
            print(f"health:   [{r.status.value}] {r.layer.value}/{r.name}: {r.detail}",
                  file=sys.stderr)
    if report.remediated:
        print(f"health: remediated: {', '.join(report.remediated)}", file=sys.stderr)


def main() -> int:
    settings = load_settings()
    report = heal_and_recheck(settings, time.time())
    write_status(report)
    log_report(report)
    if report.healthy:
        clear_safe_mode()
    else:
        enter_safe_mode(report)
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
