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


def test_cli_runs_the_real_registry_off_pi(tmp_path, monkeypatch):
    """Drive cli.main() through the REAL ALL_CHECKS/heal path (not a mocked report),
    stubbing only the systemctl layer. Off-Pi the edge brain is down → degraded."""
    status, flag = _patch_paths(tmp_path, monkeypatch)
    # No real services touched, and _unit_installed=False → no settle-sleep.
    monkeypatch.setattr("freedroid.health.remediation.run", lambda *a, **k: (127, "", ""))
    monkeypatch.delenv("FREEDROID_ASSUME_PI", raising=False)
    # A hálózat KIVEZETVE a tesztből. Enélkül az eredmény attól függött, fut-e épp egy
    # Ollama a fejlesztőgépen — 2026-08-18-án futott, és a teszt emiatt bukott. Egy
    # környezetfüggő teszt rosszabb, mint a hiányzó teszt: hol zöld, hol piros, és
    # egyik állapota sem mond semmit a kódról.
    monkeypatch.setattr("freedroid.health.checks.http_get", lambda u, **k: (0, ""))

    rc = cli.main()

    assert rc == 1  # edge Ollama unreachable on a dev box → vital failure
    data = json.loads(status.read_text())
    assert data["healthy"] is False
    assert flag.exists()


# --- a safe-mode írás szerződése (a Pi-n mérve, 2026-08-18) ---

def test_kiirhatatlan_safe_mode_jelzo_nem_traceback_hanem_exit_2(tmp_path, monkeypatch,
                                                                 capsys):
    """A `safemode` szándékosan dob, ha a jelzőt nem tudja kiírni — a hívónak ezt
    HARD FAILKÉNT kell felszínre hoznia. Eddig nyers tracebackként szállt ki.

    A Pi-n ez élesben elő is jött (`creator`-ként futtatva a root tulajdonú
    /run/freedroid alá): a 10 percenként futó timer minden körben tracebacket írt
    volna a journalba, ÉS az egyetlen fontos mondat — hogy a safe mode nem lett
    rögzítve, tehát a mozgás nem lesz letiltva — sehol nem hangzott el.
    """
    _patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("freedroid.health.remediation.run", lambda *a, **k: (127, "", ""))
    monkeypatch.delenv("FREEDROID_ASSUME_PI", raising=False)
    monkeypatch.setattr("freedroid.health.checks.http_get", lambda u, **k: (0, ""))

    def nem_irhato(report, flag_path=None):
        raise PermissionError(13, "Permission denied", "/run/freedroid/safe_mode.tmp.1")
    monkeypatch.setattr(cli, "enter_safe_mode", nem_irhato)

    assert cli.main() == 2          # nem 1: ez a ROSSZABB állapot
    hiba = capsys.readouterr().err
    assert "A SAFE MODE JELZŐ NEM ÍRHATÓ" in hiba
    assert "mozgás NEM lesz letiltva" in hiba


def test_a_torolhetetlen_jelzo_is_exit_2(tmp_path, monkeypatch, capsys):
    """A kilépési kód MINDKÉT irányban tükrözze a valóságot.

    Egészséges robot + bent ragadt safe-mode jelző = az orchestrátor nem mozog.
    A 0 ("egészséges") ilyenkor az ellenkezőjét állítaná a valóságnak.
    """
    _patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("freedroid.health.remediation.run", lambda *a, **k: (0, "active\n", ""))
    monkeypatch.setattr(cli, "heal_and_recheck",
                        lambda s, t: HealthReport(generated_at=t, results=[]))

    def nem_torolheto(flag_path=None):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(cli, "clear_safe_mode", nem_torolheto)

    assert cli.main() == 2
    hiba = capsys.readouterr().err
    assert "NEM TÖRÖLHETŐ" in hiba and "safe mode-ban marad" in hiba
