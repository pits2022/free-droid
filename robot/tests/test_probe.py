"""Low-level probe helpers — the real branching logic monkeypatched away elsewhere."""

from __future__ import annotations

from freedroid.health import probe


def test_run_missing_binary_returns_127():
    rc, out, err = probe.run(["/definitely/not/a/real/binary"])
    assert rc == 127 and out == ""


def test_run_success():
    rc, out, _ = probe.run(["printf", "hello"])
    assert rc == 0 and out == "hello"


def test_http_get_connection_refused_returns_zero():
    # Nothing listening on this port → URLError → (0, "")
    code, body = probe.http_get("http://127.0.0.1:1/", timeout=1.0)
    assert code == 0 and body == ""


def test_read_text_missing_returns_none():
    assert probe.read_text("/definitely/not/a/real/path") is None


def test_is_pi_env_override(monkeypatch):
    monkeypatch.setenv("FREEDROID_ASSUME_PI", "1")
    assert probe.is_pi() is True


def test_is_pi_false_when_all_signals_unreadable(monkeypatch):
    monkeypatch.delenv("FREEDROID_ASSUME_PI", raising=False)

    def fake_open(*_a, **_k):
        raise OSError("unreadable")

    monkeypatch.setattr("builtins.open", fake_open)
    assert probe.is_pi() is False
