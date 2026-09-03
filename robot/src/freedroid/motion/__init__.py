"""Motion control — the deterministic "body" layer (Cytron HAT-MDD10 via lgpio).

The LLM never calls this directly; the tools layer does, after parsing a <tool> call
and resolving raw strings into the enums in `motion.types`.

A vezérlő KÉT dolgot ad a biztonsági rétegnek, és csak ezt a kettőt: `heading`
(merre megyünk) és `is_turning`. A `safety/` ebből dönt, hogy melyik szenzor
állíthat meg — saját nyilvántartást NEM vezet (egyetlen forrás).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from freedroid.config import gpio as G
from freedroid.config.settings import load_settings
from freedroid.hw import open_gpiochip
from freedroid.motion.types import SPEED_DUTY, Direction, Mode, Speed, StopCond, TurnDir

if TYPE_CHECKING:
    from freedroid.config.settings import MotionSettings, Settings


def _pct(duty: float, trim: float) -> float:
    """Kitöltés százalékban, oldalankénti trimmel — 0-100 közé vágva.

    A vágás nem elméleti: egy 1.0 fölé csúszott trim némán 100%-nál telítődne, és a
    robot ugyanúgy húzna, miközben a config szerint "kalibrálva" van.
    """
    return min(100.0, max(0.0, duty * trim * 100.0))


def run_seconds(amount: float, per_second_at_full: float, duty: float) -> float:
    """Mennyi ideig hajtsunk `amount` egységnyi utat/szöget `duty` kitöltéssel.

    Külön függvény, mert ez az egyetlen SZÁMOLÁS a modulban — hardver nélkül is
    tesztelhető, és a kalibrációs értékek cseréjekor itt látszik, mi romlott el.
    """
    if duty <= 0:
        raise ValueError("duty must be > 0 to cover any distance")
    return abs(amount) / (per_second_at_full * duty)


class MotionController(Protocol):
    """Deterministic track control. Mirrors the move/turn/stop/set_speed tool grammar.

    All params are optional because the grammar allows mode-only forms
    (e.g. ``move(mode="approach_speaker")``, ``turn(mode="face_audience")``).
    """

    def move(self, direction: Direction | None = None, distance: float | None = None,
             speed: Speed | None = None, mode: Mode | None = None,
             until: StopCond | None = None) -> None: ...

    def turn(self, direction: TurnDir | None = None, degrees: float | None = None,
             mode: Mode | None = None) -> None: ...

    def stop(self) -> None: ...

    def set_speed(self, speed: Speed) -> None:
        """Set the default cruise speed (qualitative; resolved via types.SPEED_DUTY)."""
        ...

    @property
    def heading(self) -> Direction | None:
        """Merre halad ÉPPEN — `None`, ha áll vagy fordul (a hívó ezt szigorúan vegye)."""
        ...

    @property
    def is_turning(self) -> bool: ...


class CytronMotionController:
    """lgpio-backed implementation (Pi-only).

    A lábak és az irány-polaritás a `config.gpio`-ból jönnek, mert azok MÉRT
    hardver-tények (oldalanként külön "előre" szint — a motorok tükörképben ülnek).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        import lgpio  # Pi-only, ezért lusta import: a csomag off-Pi is importálható

        self._lgpio = lgpio
        self._cfg: MotionSettings = (settings or load_settings()).motion
        self._duty = self._cfg.default_speed
        self._heading: Direction | None = None
        self._turning = False
        # A megállás jelzése. Az `Event.wait(timeout)` MEGSZAKÍTHATÓ alvás: a watchdog
        # szála a `stop()`-pal azonnal kirántja a menetből a `move()`-ot, ahelyett hogy
        # az kialudná a hátralévő menetidőt egy akadály előtt.
        self._interrupt = threading.Event()
        # A lábak állítása és az állapot együtt, ATOMIAN. Enélkül van egy ablak, amiben
        # a watchdog megállít, a `_run` pedig UTÁNA adja ki a PWM-et — azaz a robot a
        # megállítás után indul el. Pont az az ablak, aminek a lezárása a watchdog
        # egyetlen feladata. A zárban SOHA nincs alvás (a menetidőt a `wait()` tölti,
        # a záron kívül), tehát a watchdog szála nem tud rajta beragadni.
        self._lock = threading.Lock()

        self._h = open_gpiochip()
        for pin in (G.LEFT_MOTOR_PWM, G.LEFT_MOTOR_DIR, G.RIGHT_MOTOR_PWM, G.RIGHT_MOTOR_DIR):
            lgpio.gpio_claim_output(self._h, pin, 0)

    # --- amit a safety/ olvas ---

    @property
    def heading(self) -> Direction | None:
        return self._heading

    @property
    def is_turning(self) -> bool:
        return self._turning

    # --- vezérlés ---

    def move(self, direction: Direction | None = None, distance: float | None = None,
             speed: Speed | None = None, mode: Mode | None = None,
             until: StopCond | None = None) -> None:
        if mode is not None:
            # A `move(mode=approach_speaker)` kamerát/követést igényel — Phase 4.4.
            # Hangosan bukik, nem néma no-op: egy csendben elnyelt tool-hívás a
            # demón úgy néz ki, mintha a robot nem értené a parancsot.
            raise NotImplementedError(f"Phase 4.4: move(mode={mode.value}) needs vision")
        if direction is None:
            raise ValueError("move() needs a direction (or a mode, once implemented)")

        duty = SPEED_DUTY[speed] if speed is not None else self._duty
        forward = direction is Direction.FORWARD
        left = G.LEFT_FORWARD_LEVEL if forward else G.LEFT_FORWARD_LEVEL ^ 1
        right = G.RIGHT_FORWARD_LEVEL if forward else G.RIGHT_FORWARD_LEVEL ^ 1

        # A távolság MÉTERBEN jön a nyelvtanból (`move forward 2`); a kalibráció cm/s.
        seconds = (run_seconds(distance * 100.0, self._cfg.cm_per_s_at_full, duty)
                   if distance is not None else self._cfg.max_run_s)
        self._run(left, right, duty, seconds, heading=direction, turning=False)

    def turn(self, direction: TurnDir | None = None, degrees: float | None = None,
             mode: Mode | None = None) -> None:
        if mode is not None:
            raise NotImplementedError(f"Phase 4.4: turn(mode={mode.value}) needs vision")
        if direction is None:
            raise ValueError("turn() needs a direction (or a mode, once implemented)")

        # Helyben fordulás: a két oldal EGYMÁSSAL SZEMBEN forog. Balra = a bal lánctalp
        # hátra, a jobb előre. Ezért kell oldalanként külön "előre" szint (config/gpio.py).
        left_fwd = direction is TurnDir.RIGHT
        left = G.LEFT_FORWARD_LEVEL if left_fwd else G.LEFT_FORWARD_LEVEL ^ 1
        right = G.RIGHT_FORWARD_LEVEL ^ 1 if left_fwd else G.RIGHT_FORWARD_LEVEL

        # Fordulásnál a `turn_duty`, nem a beállított fokozat: a helyben fordulás
        # súrlódása többszörös (mérve: 0,6-on megfeszül). A menetidő ugyanúgy a
        # dutyval skálázódik, tehát a fok fok marad.
        duty = self._cfg.turn_duty
        seconds = (run_seconds(degrees, self._cfg.deg_per_s_at_full, duty)
                   if degrees is not None else self._cfg.max_run_s)
        self._run(left, right, duty, seconds, heading=None, turning=True)

    def stop(self) -> None:
        """Feltétel nélküli megállás. A watchdog szálából is hívható, bármikor.

        Sign-Magnitude módban a `PWM = 0` a DIR állapotától FÜGGETLENÜL megállít, tehát
        a megállás oldalanként EGY írás egy lábra — nincs olyan köztes állapot, amiben
        egy félig lefutott `stop()` mozgást hagyna hátra.
        """
        # A jelzés a záron KÍVÜL, ELSŐKÉNT: így egy épp induló `_run` a záron belül már
        # beállítva látja, és el sem indítja a motorokat.
        self._interrupt.set()
        with self._lock:
            self._heading = None
            self._turning = False
            for pwm in (G.LEFT_MOTOR_PWM, G.RIGHT_MOTOR_PWM):
                # Oldalanként külön try: az egyik láb hibája nem hagyhatja járni a másikat.
                try:
                    self._lgpio.tx_pwm(self._h, pwm, self._cfg.pwm_frequency_hz, 0)
                except Exception:  # noqa: BLE001 — best-effort, de MINDKÉT oldalra
                    pass

    def set_speed(self, speed: Speed) -> None:
        self._duty = SPEED_DUTY[speed]

    def close(self) -> None:
        self.stop()
        try:
            self._lgpio.gpiochip_close(self._h)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    # --- belső ---

    def _run(self, left_level: int, right_level: int, duty: float, seconds: float,
             heading: Direction | None, turning: bool) -> None:
        self._interrupt.clear()
        with self._lock:
            # Amíg a zárat vártuk, a watchdog megállíthatott. Akkor EL SEM INDULUNK —
            # különben a `stop()` utáni PWM-írásunk visszaindítaná a robotot.
            if self._interrupt.is_set():
                return
            # SORREND: előbb az irány, aztán a PWM — fordítva a motor egy pillanatra a
            # KORÁBBI irányba indulna el.
            self._heading = heading
            self._turning = turning
            self._lgpio.gpio_write(self._h, G.LEFT_MOTOR_DIR, left_level)
            self._lgpio.gpio_write(self._h, G.RIGHT_MOTOR_DIR, right_level)
            # Az indítás: LÖKÉS (kick), ha van — a tapadási súrlódás átlépéséhez.
            self._pwm(max(duty, self._cfg.kick_duty) if self._cfg.kick_s > 0 else duty)
        seconds = min(seconds, self._cfg.max_run_s)
        # A három szakasz hossza ELŐRE, úgy, hogy az összegük PONTOSAN `seconds` legyen
        # (PR #107 review: az első változatban egy rövid menet a kért idő DUPLÁJÁIG
        # ment, mert a lökés és a rámpa is külön-külön `seconds`-ig futhatott). A
        # rámpa lépésszáma legalább 1: egy 20 ms alatti rámpa különben kimaradt volna.
        kick_time = min(self._cfg.kick_s, seconds) if self._cfg.kick_s > 0 else 0.0
        remaining = seconds - kick_time
        ramp_time = min(self._cfg.ramp_s, remaining, self._cfg.ramp_max_share * seconds)
        # A rámpa a padlóig (nem 0-ig), és az elveszett hajtás vissza az utazó szakaszba:
        # a rámpa átlagos dutyja (duty+padló)/2, a hiány ramp_time × (1 − átlag/duty).
        floor = min(self._cfg.ramp_floor_duty, duty)
        lost = ramp_time * (1.0 - (duty + floor) / (2.0 * duty)) if duty > 0 else 0.0
        cruise_time = remaining - ramp_time + lost
        try:
            # A menet SZAKASZAI, mind megszakítható alvással a záron KÍVÜL (a watchdog
            # `stop()`-ja azonnal kirántja, és nem kell a zárra várnia): lökés → utazó →
            # lineáris rámpa 0-ra. A rámpa a menetidőn BELÜL van, tehát a távolság kicsit
            # rövidül — ez a kalibráció (`cm_per_s_at_full`) dolga, nem külön korrekció.
            if kick_time > 0:
                if self._interrupt.wait(kick_time):
                    return
                if not self._pwm_ha_szabad(duty):
                    return
            if cruise_time > 0 and self._interrupt.wait(cruise_time):
                return
            if ramp_time > 0:
                n = max(1, int(ramp_time / 0.02))
                lepes = ramp_time / n
                for i in range(1, n + 1):
                    if self._interrupt.wait(lepes):
                        return
                    if not self._pwm_ha_szabad(duty - (duty - floor) * i / n):
                        return
        finally:
            self.stop()

    def _pwm(self, duty: float) -> None:
        """Mindkét oldal PWM-je az oldalankénti trimmel — EGY helyen, a `move` és a
        `turn` ugyanazon az úton megy. A hívó tartja a zárat."""
        freq = self._cfg.pwm_frequency_hz
        self._lgpio.tx_pwm(self._h, G.LEFT_MOTOR_PWM, freq, _pct(duty, self._cfg.left_duty_trim))
        self._lgpio.tx_pwm(self._h, G.RIGHT_MOTOR_PWM, freq, _pct(duty, self._cfg.right_duty_trim))

    def _pwm_ha_szabad(self, duty: float) -> bool:
        """PWM-írás a záron belül, CSAK ha közben nem állítottak meg: egy `stop()` utáni
        rámpa-lépés különben visszaindítaná a robotot — pont a watchdog ablakában."""
        with self._lock:
            if self._interrupt.is_set():
                return False
            self._pwm(duty)
            return True
