"""CLI flow — status file written, safe-mode set/cleared, exit code, end to end."""

from __future__ import annotations

import json

from freedroid.health import cli, safemode
from freedroid.health.model import HealthReport, Layer, Severity, fail, ok


def _patch_paths(tmp_path, monkeypatch):
    status = tmp_path / "health.json"
    flag = tmp_path / "safe_mode"
    monkeypatch.setattr(cli, "STATUS_PATH", str(status))
    monkeypatch.setattr(safemode, "SAFE_MODE_FLAG", str(flag))
    return status, flag


def test_healthy_run_writes_status_and_clears_safe_mode(tmp_path, monkeypatch):
    status, flag = _patch_paths(tmp_path, monkeypatch)
    flag.write_text("stale safe-mode from before\n")
    rep = HealthReport(results=(ok("a", Layer.SOFTWARE, Severity.CRITICAL),), generated_at=1.0)
    monkeypatch.setattr(cli, "heal_and_recheck", lambda settings, now: rep)

    rc = cli.main()

    assert rc == 0
    assert json.loads(status.read_text())["healthy"] is True
    assert not flag.exists()  # cleared on recovery


def test_unhealthy_run_sets_safe_mode_and_exits_1(tmp_path, monkeypatch):
    status, flag = _patch_paths(tmp_path, monkeypatch)
    rep = HealthReport(
        results=(fail("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL, "offline brain"),),
        generated_at=1.0,
    )
    monkeypatch.setattr(cli, "heal_and_recheck", lambda settings, now: rep)

    rc = cli.main()

    assert rc == 1
    assert flag.exists()
    assert "edge_ollama" in flag.read_text()
    assert json.loads(status.read_text())["healthy"] is False
