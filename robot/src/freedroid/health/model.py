"""Health-check data model.

Pure data + policy — no hardware, no I/O — so it is fully unit-testable off-Pi.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"        # degraded but the droid still functions (e.g. cloud down)
    FAIL = "fail"        # the check failed
    SKIPPED = "skipped"  # not applicable here (e.g. hardware check run off-Pi)


class Severity(str, Enum):
    CRITICAL = "critical"  # a vital function — FAIL triggers remediation then safe-mode
    WARNING = "warning"    # nice-to-have — FAIL is logged, behaviour unchanged


class Layer(str, Enum):
    NETWORK = "network"
    HARDWARE = "hardware"
    SOFTWARE = "software"


@dataclass(frozen=True)
class CheckResult:
    name: str
    layer: Layer
    status: Status
    severity: Severity = Severity.WARNING
    detail: str = ""
    # Key into the remediation registry; set when a self-heal action exists.
    remediation: str | None = None

    @property
    def is_critical_failure(self) -> bool:
        return self.severity is Severity.CRITICAL and self.status is Status.FAIL


@dataclass(frozen=True)
class HealthReport:
    results: tuple[CheckResult, ...] = ()
    generated_at: float = 0.0  # epoch seconds; injected by the caller (testable)
    remediated: tuple[str, ...] = ()  # remediation keys that were attempted

    def critical_failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.is_critical_failure]

    @property
    def healthy(self) -> bool:
        """No vital function is failing (warnings/skips don't count)."""
        return not self.critical_failures()

    @property
    def worst_status(self) -> Status:
        order = [Status.OK, Status.SKIPPED, Status.WARN, Status.FAIL]
        worst = Status.OK
        for r in self.results:
            if order.index(r.status) > order.index(worst):
                worst = r.status
        return worst

    def exit_code(self) -> int:
        """0 = healthy (warnings allowed), 1 = a vital function is down."""
        return 0 if self.healthy else 1

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "healthy": self.healthy,
            "worst_status": self.worst_status.value,
            "remediated": list(self.remediated),
            "results": [asdict_enum(r) for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        verdict = "HEALTHY" if self.healthy else "DEGRADED/CRITICAL"
        return f"{verdict} ({parts})"


def asdict_enum(result: CheckResult) -> dict:
    """asdict with Enum members rendered as their values (JSON-friendly)."""
    d = asdict(result)
    for k, v in d.items():
        if isinstance(v, Enum):
            d[k] = v.value
    return d


def ok(name: str, layer: Layer, severity: Severity = Severity.WARNING,
       detail: str = "") -> CheckResult:
    return CheckResult(name, layer, Status.OK, severity, detail)


def fail(name: str, layer: Layer, severity: Severity, detail: str,
         remediation: str | None = None) -> CheckResult:
    return CheckResult(name, layer, Status.FAIL, severity, detail, remediation)


def warn(name: str, layer: Layer, detail: str) -> CheckResult:
    return CheckResult(name, layer, Status.WARN, Severity.WARNING, detail)


def skipped(name: str, layer: Layer, detail: str = "") -> CheckResult:
    return CheckResult(name, layer, Status.SKIPPED, Severity.WARNING, detail)
