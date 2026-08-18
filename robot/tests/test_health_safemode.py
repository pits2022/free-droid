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


# --- PR #89/#88 review ---

def test_egyidejuleg_ket_iras_nem_ronja_egymast(tmp_path):
    """A tmp-név PID alapú volt, és a folyamat MINDEN szála ugyanazt a PID-et látja —
    két párhuzamos írás ugyanarra a fájlra egymás tmp-jét írta volna."""
    import threading

    from freedroid.health.safemode import write_durably

    cel = str(tmp_path / "flag")
    hibak: list[BaseException] = []

    def ir(n: int) -> None:
        try:
            for _ in range(20):
                write_durably(cel, f"{n}\n" * 500)
        except BaseException as e:  # noqa: BLE001 — a szálból ki kell hozni
            hibak.append(e)

    szalak = [threading.Thread(target=ir, args=(n,)) for n in range(4)]
    for t in szalak:
        t.start()
    for t in szalak:
        t.join()

    assert not hibak, hibak
    # Az eredmény EGYETLEN író teljes tartalma — nem kevert, nem csonka.
    sorok = set(open(cel).read().splitlines())
    assert len(sorok) == 1
    # És nem hagytunk szemetet a könyvtárban.
    assert [p.name for p in tmp_path.iterdir()] == ["flag"]


def test_a_torles_hibaja_DOB_hogy_a_hivo_felszinre_hozza(tmp_path, monkeypatch):
    """A testvérével azonos szerződés. Korábban csak figyelmeztetett, és a `main`
    0-val (= egészséges) tért vissza, miközben a bent ragadt jelző miatt az
    orchestrátor safe mode-ban maradt volna."""
    import os

    from freedroid.health.safemode import clear_safe_mode

    def tilos(_p):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(os, "remove", tilos)
    with pytest.raises(PermissionError):
        clear_safe_mode(str(tmp_path / "flag"))
