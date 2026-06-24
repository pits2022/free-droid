"""Self-healing actions, attempted before falling back to safe-mode.

Each remediation is bounded and idempotent (a single systemctl restart). Keyed by
the string a CheckResult carries in its `remediation` field.
"""

from __future__ import annotations

from freedroid.health.checks import (
    SERVICE_OLLAMA,
    SERVICE_ORCHESTRATOR,
    SERVICE_WIREGUARD,
)
from freedroid.health.probe import run

# remediation key -> systemctl restart command
REMEDIATIONS: dict[str, list[str]] = {
    "restart_wireguard": ["systemctl", "restart", SERVICE_WIREGUARD],
    "restart_ollama": ["systemctl", "restart", SERVICE_OLLAMA],
    "restart_orchestrator": ["systemctl", "restart", SERVICE_ORCHESTRATOR],
}

# `systemctl restart` blocks until the unit is active; a cold Ollama model load
# can take well over 30s, so allow generous time before calling it failed.
RESTART_TIMEOUT = 120.0


def _unit_installed(unit: str) -> bool:
    rc, out, _ = run(["systemctl", "list-unit-files", unit], timeout=10.0)
    return rc == 0 and unit.split("@")[0] in out


def remediate(key: str) -> bool:
    """Attempt the self-heal for `key`. Returns True if the action ran cleanly."""
    cmd = REMEDIATIONS.get(key)
    if cmd is None:
        return False
    # Don't churn a restart for a unit that isn't installed yet (e.g. the
    # orchestrator service before Phase 4.3). Reported as un-healed -> the droid
    # correctly stays in safe-mode, but we avoid a pointless privileged restart.
    if not _unit_installed(cmd[-1]):
        return False
    rc, _, _ = run(cmd, timeout=RESTART_TIMEOUT)
    return rc == 0
