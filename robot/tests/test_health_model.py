"""Health report logic — the pure policy that decides healthy/exit-code/safe-mode."""

from __future__ import annotations

import json

from freedroid.health.model import (
    CheckResult,
    HealthReport,
    Layer,
    Severity,
    Status,
    fail,
    ok,
    skipped,
    warn,
)


def _report(*results: CheckResult, remediated=()) -> HealthReport:
    return HealthReport(results=tuple(results), generated_at=123.0, remediated=remediated)


def test_all_ok_is_healthy():
    r = _report(ok("a", Layer.SOFTWARE, Severity.CRITICAL), ok("b", Layer.NETWORK))
    assert r.healthy
    assert r.exit_code() == 0
    assert r.worst_status is Status.OK


def test_critical_failure_is_unhealthy():
    r = _report(fail("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL, "down"))
    assert not r.healthy
    assert r.exit_code() == 1
    assert [c.name for c in r.critical_failures()] == ["edge_ollama"]


def test_warning_failure_does_not_make_unhealthy():
    # cloud down is WARNING severity -> still healthy (edge fallback covers it)
    r = _report(fail("cloud_ollama", Layer.NETWORK, Severity.WARNING, "down"))
    assert r.healthy
    assert r.exit_code() == 0


def test_skipped_and_warn_do_not_fail():
    r = _report(skipped("gpio", Layer.HARDWARE), warn("temp", Layer.HARDWARE, "hot"))
    assert r.healthy


def test_worst_status_ordering():
    r = _report(ok("a", Layer.SOFTWARE), warn("b", Layer.HARDWARE, "x"),
                skipped("c", Layer.HARDWARE))
    assert r.worst_status is Status.WARN


def test_to_json_is_serialisable_and_enum_free():
    r = _report(ok("a", Layer.SOFTWARE, Severity.CRITICAL),
                fail("b", Layer.SOFTWARE, Severity.CRITICAL, "down", remediation="restart_ollama"),
                remediated=("restart_ollama",))
    data = json.loads(r.to_json())
    assert data["healthy"] is False
    assert data["remediated"] == ["restart_ollama"]
    res = {x["name"]: x for x in data["results"]}
    assert res["a"]["status"] == "ok" and res["a"]["layer"] == "software"
    assert res["b"]["remediation"] == "restart_ollama"


def test_summary_mentions_verdict():
    assert "HEALTHY" in _report(ok("a", Layer.SOFTWARE)).summary()
    assert "CRITICAL" in _report(
        fail("a", Layer.SOFTWARE, Severity.CRITICAL, "x")).summary()
