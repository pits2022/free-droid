"""Safe-mode flag — the fallback when self-healing didn't restore a vital function.

Writes a flag file that the orchestrator (Phase 4) reads to disable motion and use
canned replies. Driving the WS2812 error colour is a Phase-4 hook (LED controller
not implemented yet).
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freedroid.health.model import HealthReport

SAFE_MODE_FLAG = os.environ.get("FREEDROID_SAFE_MODE_FLAG", "/run/freedroid/safe_mode")


def enter_safe_mode(report: HealthReport, flag_path: str | None = None) -> None:
    """Record safe-mode with the failing vital functions. Defensive (never raises)."""
    flag_path = flag_path or SAFE_MODE_FLAG
    reasons = "\n".join(f"{r.name}: {r.detail}" for r in report.critical_failures())
    try:
        os.makedirs(os.path.dirname(flag_path), exist_ok=True)
        with open(flag_path, "w") as fh:
            fh.write(reasons + "\n")
    except OSError as e:  # pragma: no cover - defensive
        print(f"health: cannot write safe-mode flag {flag_path}: {e}", file=sys.stderr)
    print("health: ENTERING SAFE MODE — vital functions down:", file=sys.stderr)
    for line in reasons.splitlines():
        print(f"health:   {line}", file=sys.stderr)
    # TODO(Phase 4): drive the WS2812 ring to the error state here.


def clear_safe_mode(flag_path: str | None = None) -> None:
    """Remove the safe-mode flag once vital functions are healthy again."""
    flag_path = flag_path or SAFE_MODE_FLAG
    try:
        os.remove(flag_path)
    except FileNotFoundError:
        pass
    except OSError as e:  # pragma: no cover - defensive
        print(f"health: cannot clear safe-mode flag {flag_path}: {e}", file=sys.stderr)
