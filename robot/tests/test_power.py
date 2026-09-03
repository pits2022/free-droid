"""Akku-őr: nyers→volt átváltás, health-check szintek, orchestrator tiltás + kimondás."""
from __future__ import annotations

import pytest

from freedroid.config.settings import PowerSettings, load_settings
from freedroid.health import checks
from freedroid.health.model import Severity, Status
from freedroid.orchestrator import AKKU_KRITIKUS_VALASZ, Orchestrator
from freedroid.power import volt_from_raw


class HamisMotion:
    heading, is_turning = None, False

    def stop(self) -> None: ...

    def close(self) -> None: ...


class HamisWatchdog:
    fault = None

    def start(self) -> None: ...

    def stop_monitoring(self) -> None: ...


def test_volt_from_raw_a_mert_ertekkel():
    # 2026-09-03, i2cget ±6,144 V-on: nyers 16764 = 0x417C → 3,143 V az AIN0-n, ×3,91 = 12,29 V
    assert volt_from_raw(0x41, 0x7C, 3.91) == pytest.approx(12.29, abs=0.01)
    assert volt_from_raw(0xFF, 0xFF, 3.91) < 0            # előjeles: -1 LSB


def test_power_settings_kuszobok():
    p = PowerSettings()
    assert (p.warn_v, p.critical_v) == pytest.approx((10.2, 9.6))
    with pytest.raises(ValueError):
        PowerSettings(critical_v_per_cell=3.5)             # crit >= warn


@pytest.mark.parametrize("v, status, sev", [
    (12.3, Status.OK, Severity.WARNING),
    (10.0, Status.WARN, Severity.WARNING),
    (9.5, Status.FAIL, Severity.CRITICAL),
])
def test_check_battery_szintek(monkeypatch, v, status, sev):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    import freedroid.power
    monkeypatch.setattr(freedroid.power, "read_battery_v", lambda s: v)
    r = checks.check_battery(load_settings())
    assert (r.status, r.severity) == (status, sev)


def test_check_battery_hianyzo_mero_csak_warning(monkeypatch):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    import freedroid.power

    def nincs(s):
        raise OSError("no such device")
    monkeypatch.setattr(freedroid.power, "read_battery_v", nincs)
    r = checks.check_battery(load_settings())
    assert (r.status, r.severity) == (Status.WARN, Severity.WARNING)


class HamisTTS:
    def __init__(self) -> None:
        self.mondott: list[str] = []

    def speak(self, s: str) -> None:
        self.mondott.append(s)


def test_orchestrator_kritikus_akku_tilt_es_egyszer_szol():
    ertek = [9.0]
    o = Orchestrator(motion=HamisMotion(), watchdog=HamisWatchdog(), llm=object(),
                     akku_olvaso=lambda: ertek[0])
    tts = HamisTTS()
    assert not o._mozgas_tiltott()
    o._akku_ellenor(tts, most=100.0)
    assert o._mozgas_tiltott()
    assert tts.mondott == [AKKU_KRITIKUS_VALASZ]
    o._akku_ellenor(tts, most=200.0)               # még mindig kritikus: nem ismétli
    assert tts.mondott == [AKKU_KRITIKUS_VALASZ]
    o._akku_ellenor(tts, most=210.0)               # 60 s-en belül: nem is olvas
    ertek[0] = 9.7                                 # a hiszterézis alatt (9,6+0,3=9,9)
    o._akku_ellenor(tts, most=300.0)
    assert o._mozgas_tiltott()
    ertek[0] = 12.3                                # akkucsere
    o._akku_ellenor(tts, most=400.0)
    assert not o._mozgas_tiltott()


def test_orchestrator_olvashatatlan_mero_nem_tilt():
    def nincs():
        raise OSError("no i2c")
    o = Orchestrator(motion=HamisMotion(), watchdog=HamisWatchdog(), llm=object(),
                     akku_olvaso=nincs)
    o._akku_ellenor(HamisTTS(), most=100.0)
    assert not o._mozgas_tiltott()
