"""A watchdog KÉT szabálya, hardver nélkül.

A GPIO-t igénylő rész a `test_phase4_hardware.py`-ban van (Pi-only). Ami itt van, az a
két DÖNTÉS — irány-függő megállás és min(3) —, és pont ezek azok, amiket egy elrontott
refaktor csendben visszafordíthat.
"""

from __future__ import annotations

import math
import threading
import time

import pytest

from freedroid.config import gpio as G
from freedroid.config.settings import MotionSettings, SafetySettings
from freedroid.motion import CytronMotionController, run_seconds
from freedroid.motion.types import Direction
from freedroid.safety import FRONT, REAR, UltrasonicWatchdog, relevant_sensors
from freedroid.safety.ranging import MIN_SAMPLES, combine


class TestIranyFuggoMegallas:
    def test_elore_csak_az_elulso_allit_meg(self):
        assert relevant_sensors(Direction.FORWARD) == {FRONT}

    def test_hatra_csak_a_hatso_allit_meg(self):
        # Ez a szabály lényege: háttal a falnak a robot EL TUD indulni előre.
        assert relevant_sensors(Direction.BACKWARD) == {REAR}

    def test_ismeretlen_irany_eseten_mindketto(self):
        # Fail-safe: a hiba a felesleges fékezés felé essen, ne a mozgás felé.
        assert relevant_sensors(None) == set(G.ULTRASONIC)

    def test_fordulas_kozben_egyik_sem(self):
        # Ismert vak eset: a súrolt ívet egyik szenzor sem látja, a megállás nem védene,
        # csak megtiltaná a faltól való elfordulást.
        assert relevant_sensors(None, turning=True) == set()

    def test_minden_figyelt_szenzor_letezik_a_kiosztasban(self):
        # Elgépelt szenzornév némán "soha nem állít meg"-et jelentene.
        for heading in (Direction.FORWARD, Direction.BACKWARD, None):
            assert relevant_sensors(heading) <= set(G.ULTRASONIC)


class TestMin3:
    def test_a_veszelyes_kilenges_kiesik(self):
        # A terhelés csak HOSSZABBNAK mutathatja az impulzust: a 73.5 cm-es túlbecslés
        # (a mért legrosszabb eset) a min() miatt nem dönt.
        assert combine([20.0, 93.5, 20.4]) == 20.0

    def test_a_nema_minta_kimarad_de_nem_nullaz(self):
        assert combine([None, 30.0, None]) == 30.0

    def test_csupa_nema_az_None(self):
        # A hívó ezt HIBAKÉNT kezeli (akadály), nem "szabad az út"-ként.
        assert combine([None, None, None]) is None

    def test_ures_ter_szabad_marad(self):
        assert combine([math.inf, math.inf, math.inf]) == math.inf

    def test_harom_minta_a_minimum(self):
        # Mérésből jött szám (docs/free-droid.md 5.), nem ízlés — ne csökkenjen.
        assert MIN_SAMPLES >= 3


class TestMenetido:
    def test_fel_kitoltessel_ketszer_annyi_ido(self):
        assert run_seconds(100, 30.0, 1.0) == pytest.approx(100 / 30.0)
        assert run_seconds(100, 30.0, 0.5) == pytest.approx(2 * 100 / 30.0)

    def test_nulla_kitoltes_hangosan_bukik(self):
        # Különben a robot "megy 2 métert" 0 sebességgel, örökre.
        with pytest.raises(ValueError):
            run_seconds(100, 30.0, 0.0)


class FakeLgpio:
    """A GPIO-hívások naplója. Nem hardver-emuláció — csak azt rögzíti, MI történt."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def gpio_write(self, h, pin, level):
        self.calls.append(("write", pin, level))

    def tx_pwm(self, h, pin, freq, duty):
        self.calls.append(("pwm", pin, duty))

    def hajtott(self) -> bool:
        """Adtunk-e ki NEM NULLA kitöltést, azaz elindult-e a robot."""
        return any(c[0] == "pwm" and c[2] > 0 for c in self.calls)


def _bare_motion(fake: FakeLgpio) -> CytronMotionController:
    """Vezérlő hardver-megnyitás nélkül — az `__init__` a gpiochipet nyitná."""
    m = object.__new__(CytronMotionController)
    m._lgpio = fake
    m._cfg = MotionSettings()
    m._h = 0
    m._duty = 0.5
    m._heading = None
    m._turning = False
    m._interrupt = threading.Event()
    m._lock = threading.Lock()
    return m


def test_a_stop_utan_a_menet_el_sem_indul():
    """A #83-as review versenyhelyzete: megállítás a menet indításának pillanatában.

    Enélkül a `_run` a `stop()` UTÁN adná ki a PWM-et — a robot a megállítás után
    indulna el. Pont az az ablak, aminek a lezárása a watchdog egyetlen feladata.
    """
    fake = FakeLgpio()
    m = _bare_motion(fake)

    m._lock.acquire()  # a zárat fogva tartjuk: itt fut a versenyhelyzet
    indit = threading.Thread(
        target=m._run, args=(1, 0, 0.5, 5.0, Direction.FORWARD, False))
    indit.start()
    time.sleep(0.05)  # a menet-szál eljut a zárig és ott vár

    megallit = threading.Thread(target=m.stop)
    megallit.start()
    time.sleep(0.05)  # a stop beállítja az _interrupt-ot, majd szintén a zárra vár

    m._lock.release()
    indit.join(timeout=2)
    megallit.join(timeout=2)

    assert not fake.hajtott(), f"a robot elindult a stop után: {fake.calls}"
    assert m.heading is None


class TestTrim:
    """A robot balra húz (MÉRVE 2026-08-17) — a trim ezt fogja vissza."""

    def _pwm(self, fake: FakeLgpio) -> dict[int, float]:
        return {c[1]: c[2] for c in fake.calls if c[0] == "pwm" and c[2] > 0}

    def test_a_trim_oldalankent_kulon_hat(self):
        fake = FakeLgpio()
        m = _bare_motion(fake)
        m._cfg = MotionSettings(left_duty_trim=1.0, right_duty_trim=0.9)
        m._run(1, 0, 0.5, 0.01, Direction.FORWARD, False)

        pwm = self._pwm(fake)
        assert pwm[G.LEFT_MOTOR_PWM] == pytest.approx(50.0)
        assert pwm[G.RIGHT_MOTOR_PWM] == pytest.approx(45.0)

    def test_a_kitoltes_100_folott_levagodik(self):
        # Enélkül egy elszállt trim némán telítődne, és a robot ugyanúgy húzna,
        # miközben a config szerint "kalibrálva" van.
        fake = FakeLgpio()
        m = _bare_motion(fake)
        m._run(1, 0, 1.0, 0.01, Direction.FORWARD, False)
        assert max(self._pwm(fake).values()) <= 100.0

    def test_a_gyorsitas_nem_engedheto(self):
        # 1.0 fölötti trim = a lassabb oldal gyorsítása, ami teljes kitöltésen
        # lehetetlen — inkább hangosan bukjon, mint csendben hatástalan legyen.
        with pytest.raises(ValueError):
            MotionSettings(right_duty_trim=1.2)


class TestTrimSzamitas:
    """A kalibrációs geometria (`scripts/calibrate_motion.py`)."""

    def _cfg(self, bal: float = 1.0, jobb: float = 1.0):
        # A trimet KIFEJEZETTEN megadjuk, nem a defaultot használjuk: a default a
        # MÉRT érték (jobb=0.92), és akkor ezek a tesztek a következő kalibrációtól
        # dőlnének el — miközben a geometriáról szólnak, nem a robot aktuális
        # állapotáról.
        return MotionSettings(track_width_cm=21.0,
                              left_duty_trim=bal, right_duty_trim=jobb)

    def test_balra_huzas_a_jobb_oldalt_lassitja(self):
        from calibrate_motion import _trim
        bal, jobb = _trim(self._cfg(), hossz_cm=200, oldal_cm=40)
        assert bal == 1.0
        assert jobb < 1.0

    def test_jobbra_huzas_a_bal_oldalt_lassitja(self):
        from calibrate_motion import _trim
        bal, jobb = _trim(self._cfg(), hossz_cm=200, oldal_cm=-40)
        assert bal < 1.0
        assert jobb == 1.0

    def test_egyenes_menet_MEGTARTJA_a_mostani_trimet(self):
        """0 elsodródás NEM azt jelenti, hogy 1.0/1.0-ra kell állni.

        A robot azért ment egyenesen, MERT a mostani trim jó — visszaállítani
        1.0/1.0-ra pont a kalibrációt dobná el, és újra húzni kezdene.
        """
        from calibrate_motion import _trim
        assert _trim(self._cfg(jobb=0.92), hossz_cm=222, oldal_cm=0) == (1.0, 0.92)

    def test_tul_nagy_elsodrodas_nem_szamolhato(self):
        # A képlet kis szögre érvényes; e fölött a szám hihető lenne, de hamis.
        from calibrate_motion import _trim
        assert _trim(self._cfg(), hossz_cm=100, oldal_cm=90) is None
        assert _trim(self._cfg(), hossz_cm=100, oldal_cm=-90) is None

    def test_az_eredmeny_mindig_ervenyes_trim(self):
        # A MotionSettings (0.0, 1.0] tartományt vár — érvénytelen érték csak a
        # robot indulásakor bukna ki, ami a legrosszabb pillanat.
        from calibrate_motion import _trim
        for oldal in (-25, -10, -1, 0, 1, 10, 25):
            bal, jobb = _trim(self._cfg(), hossz_cm=100, oldal_cm=oldal)
            MotionSettings(left_duty_trim=bal, right_duty_trim=jobb)


def _bare_watchdog(on_obstacle) -> UltrasonicWatchdog:
    wd = object.__new__(UltrasonicWatchdog)
    wd._stop_flag = threading.Event()
    wd._cfg = SafetySettings(poll_interval_s=0.001)
    wd._on_obstacle = on_obstacle
    wd._blocked = False
    wd._fault = None
    return wd


def test_a_watchdog_szal_tulel_egy_meresi_hibat():
    """A #83-as review 1. pontja: kezeletlen kivétel = CSENDBEN megszűnő védelem."""
    stops: list[int] = []
    wd = _bare_watchdog(lambda: stops.append(1))
    korok: list[int] = []

    def boom():
        korok.append(1)
        if len(korok) >= 3:
            wd._stop_flag.set()  # három kör után elég
        raise RuntimeError("lgpio ideiglenes I/O hiba")

    wd.poll_once = boom
    wd._loop()

    assert len(korok) >= 3, "a szál meghalt az első hiba után"
    assert len(stops) >= 3, "a hiba nem állította meg a robotot"
    # És kívülről is LÁTSZIK — enélkül a hibázó watchdog ugyanúgy néz ki, mint a jó.
    assert wd.is_blocked()
    assert wd.fault is not None and "lgpio" in wd.fault
