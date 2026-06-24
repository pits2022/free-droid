"""Safe-mode flag — the fallback when self-healing didn't restore a vital function.

Writes a flag file that the orchestrator (Phase 4) reads to disable motion and use
canned replies. Driving the WS2812 error colour is a Phase-4 hook (LED controller
not implemented yet).

The flag is the safety contract, so writing it is NOT best-effort: the write is
atomic + fsynced, and a failure is raised loudly rather than swallowed (a swallowed
write failure would mean "reported safe-mode but motion still enabled"). The Phase-4
orchestrator must also fail safe if the status/flag is missing or stale.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freedroid.health.model import HealthReport

SAFE_MODE_FLAG = os.environ.get("FREEDROID_SAFE_MODE_FLAG", "/run/freedroid/safe_mode")


def _write_durably(path: str, content: str) -> None:
    """Atomic, fsynced write. Raises OSError on failure (intentionally not swallowed)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, content.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def enter_safe_mode(report: HealthReport, flag_path: str | None = None) -> None:
    """Record safe-mode with the failing vital functions.

    Logs first (so the reason is always visible), then writes the flag durably.
    Raises if the flag cannot be written — the caller must surface that as a hard
    failure, never continue as if safe-mode is in effect.
    """
    flag_path = flag_path or SAFE_MODE_FLAG
    reasons = "\n".join(f"{r.name}: {r.detail}" for r in report.critical_failures())
    print("health: ENTERING SAFE MODE — vital functions down:", file=sys.stderr)
    for line in reasons.splitlines():
        print(f"health:   {line}", file=sys.stderr)
    _write_durably(flag_path, reasons + "\n")
    # TODO(Phase 4): drive the WS2812 ring to the error state here.


def clear_safe_mode(flag_path: str | None = None) -> None:
    """Remove the safe-mode flag once vital functions are healthy again."""
    flag_path = flag_path or SAFE_MODE_FLAG
    try:
        os.remove(flag_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        # A stale flag leaves the droid stuck in safe-mode — surface it loudly.
        print(f"health: WARNING cannot clear safe-mode flag {flag_path}: {e}", file=sys.stderr)
