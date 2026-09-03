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

    def test_a_nyomtavnal_rovidebb_ut_nem_szamolhato(self):
        # Ez teszi a képletet TOTÁLISSÁ: a nevező (hossz^2 + oldal*nyomtáv) csak
        # nagyon rövid úton tudna nullára/negatívra futni, és egy a saját nyomtávjánál
        # kevesebbet haladt robotnál amúgy sincs értelme "egyenességről" beszélni.
        from calibrate_motion import _trim
        assert _trim(self._cfg(), hossz_cm=15, oldal_cm=-3) is None
        assert _trim(self._cfg(), hossz_cm=0, oldal_cm=0) is None

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


def _bare_watchdog(on_obstacle=lambda: None, heading=None,
                   turning=False) -> UltrasonicWatchdog:
    """Watchdog hardver-megnyitás nélkül — az `__init__` a gpiochipet nyitná.

    EGY segédfüggvény a szál-teszthez és a mérési-szabály tesztekhez is: két azonos
    nevű változat közül a később definiált elfedi a másikat, csendben, és a hibaüzenet
    egy egészen máshová mutató AttributeError lenne.
    """
    wd = object.__new__(UltrasonicWatchdog)
    wd._lgpio = None
    wd._stop_flag = threading.Event()
    wd._cfg = SafetySettings(poll_interval_s=0.001)
    wd._on_obstacle = on_obstacle
    wd._heading_source = lambda: (heading, turning)
    wd._distances = dict.fromkeys(G.ULTRASONIC)
    wd._blocked = False
    wd._fault = None
    wd._h = 0
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


# --- HARMADIK szabály: menet közben CSAK a figyelt szenzort mérjük ------------------

def _mert_szenzorok(monkeypatch, heading, turning=False, ertek=math.inf) -> list[str]:
    """MELYIK szenzorokat mérte meg egy kör. A lábakból fejtjük vissza a nevet."""
    labbol = {p["trig"]: nev for nev, p in G.ULTRASONIC.items()}
    mertek: list[str] = []

    def hamis_meres(lgpio, h, trig, echo, **kw):
        mertek.append(labbol[trig])
        return ertek

    monkeypatch.setattr("freedroid.safety.measure_cm_min3", hamis_meres)
    _bare_watchdog(heading=heading, turning=turning).poll_once()
    return mertek


class TestCsakAFigyeltSzenzortMerjuk:
    """MÉRVE 2026-08-26: egy kör 158 ms, amiből ~114 ms azé a szenzoré, amelyik ÜRES
    teret lát (a HC-SR04 "nincs visszhang" jelzése ~38 ms, a `min(3)` háromszor fizeti).
    Előremenetben ez a HÁTSÓ szenzor — az adatát a döntés nem is használja. Emiatt járt
    a watchdog 20 Hz helyett 4,8-on, és emiatt fogyott el a fékút-büdzsé a `fast`-on.

    Ha ezek a tesztek elbuknak, a watchdog ÜTEME romlott el, nem a logikája — és az a
    fajta romlás, ami csak a következő fékút-mérésen látszana meg."""

    def test_elore_menet_csak_az_elulsot_meri(self, monkeypatch):
        assert _mert_szenzorok(monkeypatch, Direction.FORWARD) == [FRONT]

    def test_hatramenet_csak_a_hatsot_meri(self, monkeypatch):
        assert _mert_szenzorok(monkeypatch, Direction.BACKWARD) == [REAR]

    def test_allo_helyzetben_MINDKETTOT_meri(self, monkeypatch):
        # Álló helyzetben mindkettő MEGÁLLÍTHAT (fail-safe), tehát mindkettő friss kell.
        assert set(_mert_szenzorok(monkeypatch, None)) == set(G.ULTRASONIC)

    def test_forduláskor_MINDKETTOT_meri(self, monkeypatch):
        """A `watched` forduláskor ÜRES (a súrolt ívet egyik szenzor sem látja). Ha az
        üres halmazt szó szerint vennénk, a watchdog a manőver alatt semmit nem mérne,
        és utána ELAVULT adattal indulna — ott a néma vakság rosszabb, mint a plusz idő.
        """
        assert set(_mert_szenzorok(monkeypatch, None, turning=True)) == set(G.ULTRASONIC)

    def test_a_nem_mert_szenzor_erteke_MEGMARAD(self, monkeypatch):
        """A csere ára: menet közben a nem figyelt szenzor értéke elavul. Ez tudatos, és
        biztonságilag semleges (az a szenzor olyankor nem is állíthat meg) — de NEM
        `None`-ra vált, mert a `None` NÉMA SZENZORT jelent, azaz hibát jelezne ott, ahol
        csak nem mértünk."""
        labbol = {p["trig"]: nev for nev, p in G.ULTRASONIC.items()}
        wd = _bare_watchdog(heading=Direction.FORWARD)
        wd._distances[REAR] = 42.0          # egy korábbi kör mérése

        monkeypatch.setattr("freedroid.safety.measure_cm_min3",
                            lambda lgpio, h, trig, echo, **kw: 100.0
                            if labbol[trig] == FRONT else 0.0)
        wd.poll_once()
        assert wd.distances_cm()[FRONT] == 100.0
        assert wd.distances_cm()[REAR] == 42.0


def test_a_menet_lokessel_indul_es_rampaval_all_meg():
    """A Teremtő (2026-09-03): 0,5-ön nem indul, 0,8-on rángat. A profil: kick → utazó →
    lineáris rámpa 0-ra; az utolsó írás 0, és a rámpa minden lépése kisebb az előzőnél."""
    fake = FakeLgpio()
    m = _bare_motion(fake)
    m._cfg = MotionSettings(kick_duty=0.85, kick_s=0.05, ramp_s=0.1, default_speed=0.6)
    m._run(1, 1, 0.6, 0.3, heading=None, turning=False)
    bal = [c[2] for c in fake.calls if c[0] == "pwm" and c[1] == G.LEFT_MOTOR_PWM]
    assert bal[0] == pytest.approx(85.0)                    # lökés
    assert bal[1] == pytest.approx(60.0)                    # utazó
    rampa = bal[2:]
    assert rampa == sorted(rampa, reverse=True) and rampa[-1] == 0.0   # csökken, a végén stop
    assert rampa[-2] == pytest.approx(50.0)                  # a rámpa a PADLÓIG (0,5), nem 0-ig
    assert 3 <= len(rampa) <= 7                              # ~0,1 s / 20 ms lépés


def test_a_rovid_fordulasnak_marad_utazo_szakasza():
    """Mérve 2026-09-03: 90° 0,8-on 0,34 s; a lökés utáni maradék EGÉSZE rámpa volt 0-ig →
    5° a 90 helyett. A rámpa legfeljebb a menet 30%-a, a padlóig, és a hiány az utazóé."""
    fake = FakeLgpio()
    m = _bare_motion(fake)
    m._cfg = MotionSettings(kick_duty=0.85, kick_s=0.15, ramp_s=0.4, ramp_floor_duty=0.5,
                            ramp_max_share=0.3, default_speed=0.6)
    kezd = time.perf_counter()
    m._run(1, 1, 0.8, 0.344, heading=None, turning=True)
    telt = time.perf_counter() - kezd
    pwm = [c[2] for c in fake.calls if c[0] == "pwm" and c[1] == G.LEFT_MOTOR_PWM]
    assert pwm[0] == pytest.approx(85.0) and pwm[1] == pytest.approx(80.0)
    assert min(d for d in pwm if d > 0) >= 50.0              # sosem a küszöb alatt
    assert 0.34 < telt < 0.42, telt                          # + az elveszett hajtás, nem több
    # ∫duty·dt ≈ duty × menetidő, azaz a fok fok marad
    rampa_s = 0.3 * 0.344
    integral = 0.15 * 0.85 + (telt - 0.15 - rampa_s) * 0.8 + rampa_s * 0.65
    assert integral == pytest.approx(0.8 * 0.344, rel=0.08)



def test_a_stop_a_rampa_kozben_NEM_indit_ujra():
    """A rámpa lépései a záron belül nézik a jelzőt: egy `stop()` utáni írás
    visszaindítaná a robotot — a watchdog ablakában."""
    fake = FakeLgpio()
    m = _bare_motion(fake)
    m._cfg = MotionSettings(kick_duty=0.85, kick_s=0.0, ramp_s=0.3, default_speed=0.6)

    def allj():
        time.sleep(0.12)
        m.stop()
    threading.Thread(target=allj, daemon=True).start()
    m._run(1, 1, 0.6, 0.3, heading=None, turning=False)
    pwm = [c[2] for c in fake.calls if c[0] == "pwm" and c[1] == G.LEFT_MOTOR_PWM]
    utolso_nem_nulla = max(i for i, d in enumerate(pwm) if d > 0)
    assert all(d == 0.0 for d in pwm[utolso_nem_nulla + 1:])   # a stop után csak 0-k
    assert time.time()  # a menet 0,3 s alatt véget ért (különben a teszt beragadna)


def test_a_rovid_menet_NEM_hosszabb_a_kert_idonel():
    """PR #107 review: az első változatban egy 0,1 s-os menet 0,2 s-ig ment (a lökés és a
    rámpa is külön `seconds`-ig futhatott). A három szakasz összege PONTOSAN `seconds`."""
    fake = FakeLgpio()
    m = _bare_motion(fake)
    m._cfg = MotionSettings(kick_duty=0.85, kick_s=0.15, ramp_s=0.4, default_speed=0.6)
    kezd = time.perf_counter()
    m._run(1, 1, 0.6, 0.1, heading=None, turning=False)
    telt = time.perf_counter() - kezd
    assert 0.08 < telt < 0.16, telt
    # És egy 20 ms alatti rámpa sem marad ki: legalább egy lépés, ami 0-ra visz.
    fake.calls.clear()
    m._cfg = MotionSettings(kick_duty=0.85, kick_s=0.0, ramp_s=0.01, default_speed=0.6)
    m._run(1, 1, 0.6, 0.05, heading=None, turning=False)
    pwm = [c[2] for c in fake.calls if c[0] == "pwm" and c[1] == G.LEFT_MOTOR_PWM]
    assert pwm[0] == pytest.approx(60.0) and pwm[-1] == 0.0


def test_a_fordulas_a_turn_duty_val_megy_nem_a_fokozattal():
    """Mérve 2026-09-03: helyben fordulásnál a 0,6 utazó duty megfeszül. A `turn()` a
    `turn_duty`-t használja, a `set_speed` fokozata csak az egyenes menetet szabja."""
    from freedroid.motion.types import TurnDir

    fake = FakeLgpio()
    m = _bare_motion(fake)
    m._cfg = MotionSettings(kick_s=0.0, ramp_s=0.0, turn_duty=0.8, default_speed=0.6)
    m._duty = 0.6
    m.turn(TurnDir.LEFT, degrees=5)
    pwm = [c[2] for c in fake.calls if c[0] == "pwm" and c[1] == G.LEFT_MOTOR_PWM]
    assert pwm[0] == pytest.approx(80.0)
