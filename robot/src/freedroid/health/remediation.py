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


def remediate(key: str) -> bool:
    """Attempt the self-heal for `key`. Returns True if the action ran cleanly."""
    cmd = REMEDIATIONS.get(key)
    if cmd is None:
        return False
    rc, _, _ = run(cmd, timeout=30.0)
    return rc == 0
