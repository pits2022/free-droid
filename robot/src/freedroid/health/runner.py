"""Orchestration: run the checks, self-heal, re-check, then decide on safe-mode.

Pure orchestration with injectable side-effects (remediator, sleep) so the whole
heal→recheck→safe-mode flow is unit-testable without touching the system.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from freedroid.health.checks import ALL_CHECKS, Check
from freedroid.health.model import CheckResult, HealthReport, Layer, Severity, fail
from freedroid.health.remediation import remediate

if TYPE_CHECKING:
    from freedroid.config.settings import Settings

# Time to let a restarted service settle before re-checking.
SETTLE_SECONDS = 5.0


def _run_one(check: Check, settings: Settings) -> CheckResult:
    """Run a single check, turning an unexpected crash into a CRITICAL fail.

    The checks are *meant* never to raise, but enforcing it here makes the
    guarantee real: a crashing check drives safe-mode (fail-safe) instead of
    aborting the whole run before status/safe-mode are ever written.
    """
    try:
        return check(settings)
    except Exception as e:  # noqa: BLE001 - deliberate fail-safe boundary
        return fail(getattr(check, "__name__", "unknown_check"), Layer.SOFTWARE,
                    Severity.CRITICAL, f"check crashed: {e!r}")


def run_checks(settings: Settings, checks: tuple[Check, ...] = ALL_CHECKS) -> list[CheckResult]:
    return [_run_one(check, settings) for check in checks]


def build_report(settings: Settings, now: float,
                 checks: tuple[Check, ...] = ALL_CHECKS,
                 remediated: tuple[str, ...] = ()) -> HealthReport:
    return HealthReport(results=tuple(run_checks(settings, checks)),
                        generated_at=now, remediated=remediated)


def heal_and_recheck(settings: Settings, now: float,
                     checks: tuple[Check, ...] = ALL_CHECKS,
                     remediator: Callable[[str], bool] = remediate,
                     sleep: Callable[[float], None] = time.sleep,
                     settle_seconds: float = SETTLE_SECONDS) -> HealthReport:
    """Run checks once; if a VITAL function failed and is fixable, self-heal and
    re-check once. Only CRITICAL failures are remediated — a WARNING (e.g. the
    on-demand cloud / VPN being down) is expected and must not trigger a
    privileged service restart on every timer cycle."""
    first = build_report(settings, now, checks)
    keys = sorted({
        r.remediation for r in first.results
        if r.is_critical_failure and r.remediation
    })
    if not keys:
        return first

    attempted = tuple(k for k in keys if remediator(k))
    if not attempted:
        return first
    sleep(settle_seconds)  # let restarted services come up
    return build_report(settings, now, checks, remediated=attempted)
