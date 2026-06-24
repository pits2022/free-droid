"""remediate() — the real systemctl mapping (runner tests inject a fake remediator)."""

from __future__ import annotations

from freedroid.health import remediation


def test_unknown_key_returns_false_without_running(monkeypatch):
    called = []
    monkeypatch.setattr(remediation, "run", lambda *a, **k: called.append(a) or (0, "", ""))
    assert remediation.remediate("nope") is False
    assert called == []  # never shelled out


def test_known_key_restarts_when_unit_installed(monkeypatch):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[1] == "list-unit-files":
            return 0, "ollama.service enabled\n", ""
        return 0, "", ""  # the restart

    monkeypatch.setattr(remediation, "run", fake_run)
    assert remediation.remediate("restart_ollama") is True
    assert ["systemctl", "restart", "ollama"] in calls


def test_skips_restart_when_unit_not_installed(monkeypatch):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[1] == "list-unit-files":
            return 0, "", ""  # unit absent
        return 0, "", ""

    monkeypatch.setattr(remediation, "run", fake_run)
    # The orchestrator service isn't deployed until Phase 4.3 → no churn.
    assert remediation.remediate("restart_orchestrator") is False
    assert not any(c[:2] == ["systemctl", "restart"] for c in calls)


def test_restart_failure_returns_false(monkeypatch):
    def fake_run(cmd, **k):
        if cmd[1] == "list-unit-files":
            return 0, "ollama.service\n", ""
        return 1, "", "failed"

    monkeypatch.setattr(remediation, "run", fake_run)
    assert remediation.remediate("restart_ollama") is False
