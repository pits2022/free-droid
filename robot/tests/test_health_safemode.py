"""safe-mode flag — the safety contract: it must be written durably or fail loudly."""

from __future__ import annotations

import pytest

from freedroid.health.model import HealthReport, Layer, Severity, fail, ok
from freedroid.health.safemode import clear_safe_mode, enter_safe_mode


def _report(*results):
    return HealthReport(results=tuple(results), generated_at=1.0)


def test_enter_safe_mode_writes_reasons(tmp_path):
    flag = tmp_path / "safe_mode"
    rep = _report(
        fail("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL, "offline brain"),
        fail("gpio_chip", Layer.HARDWARE, Severity.CRITICAL, "no chip"),
        ok("x", Layer.SOFTWARE),  # non-critical, must not appear
    )
    enter_safe_mode(rep, str(flag))
    body = flag.read_text()
    assert "edge_ollama" in body and "gpio_chip" in body
    assert "x" not in body


def test_enter_safe_mode_raises_when_unwritable(tmp_path):
    # Parent path is a FILE, so makedirs/open must fail — and must NOT be swallowed
    # (a silent failure would mean "reported safe-mode" but no flag for the orchestrator).
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    flag = blocker / "safe_mode"
    rep = _report(fail("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL, "down"))
    with pytest.raises(OSError):
        enter_safe_mode(rep, str(flag))


def test_clear_safe_mode_removes_flag(tmp_path):
    flag = tmp_path / "safe_mode"
    flag.write_text("stale\n")
    clear_safe_mode(str(flag))
    assert not flag.exists()


def test_clear_safe_mode_noop_when_absent(tmp_path):
    clear_safe_mode(str(tmp_path / "never_existed"))  # must not raise
