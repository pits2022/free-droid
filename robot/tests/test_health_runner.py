"""heal_and_recheck — self-heal then re-check, with injected remediator + sleep."""

from __future__ import annotations

from freedroid.config.settings import load_settings
from freedroid.health.model import Layer, Severity, fail, ok
from freedroid.health.runner import heal_and_recheck

S = load_settings()
NO_SLEEP = lambda _s: None  # noqa: E731


def _flaky(state):
    """Critical-fails until state['healed'] is set, then OK."""
    def check(settings):
        if state["healed"]:
            return ok("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL)
        return fail("edge_ollama", Layer.SOFTWARE, Severity.CRITICAL,
                    "down", remediation="restart_ollama")
    return check


def test_no_remediation_when_already_healthy():
    calls = []
    checks = (lambda s: ok("x", Layer.SOFTWARE, Severity.CRITICAL),)
    rep = heal_and_recheck(S, 1.0, checks=checks,
                           remediator=lambda k: calls.append(k) or True, sleep=NO_SLEEP)
    assert rep.healthy and rep.remediated == () and calls == []


def test_heals_then_rechecks_healthy():
    state = {"healed": False}

    def remediator(key):
        assert key == "restart_ollama"
        state["healed"] = True
        return True

    rep = heal_and_recheck(S, 1.0, checks=(_flaky(state),),
                           remediator=remediator, sleep=NO_SLEEP)
    assert rep.healthy
    assert rep.remediated == ("restart_ollama",)


def test_failed_remediation_stays_unhealthy():
    state = {"healed": False}
    rep = heal_and_recheck(S, 1.0, checks=(_flaky(state),),
                           remediator=lambda k: False, sleep=NO_SLEEP)
    assert not rep.healthy
    assert rep.remediated == ()


def test_failure_without_remediation_key_not_attempted():
    called = []
    checks = (lambda s: fail("gpio_chip", Layer.HARDWARE, Severity.CRITICAL, "no chip"),)
    rep = heal_and_recheck(S, 1.0, checks=checks,
                           remediator=lambda k: called.append(k) or True, sleep=NO_SLEEP)
    assert not rep.healthy and called == []
