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

        duty = self._duty
        seconds = (run_seconds(degrees, self._cfg.deg_per_s_at_full, duty)
                   if degrees is not None else self._cfg.max_run_s)
        self._run(left, right, duty, seconds, heading=None, turning=True)

    def stop(self) -> None:
        """Feltétel nélküli megállás. A watchdog szálából is hívható, bármikor.

        Sign-Magnitude módban a `PWM = 0` a DIR állapotától FÜGGETLENÜL megállít, tehát
        a megállás oldalanként EGY írás egy lábra — nincs olyan köztes állapot, amiben
        egy félig lefutott `stop()` mozgást hagyna hátra.
        """
        self._interrupt.set()
        self._heading = None
        self._turning = False
        for pwm in (G.LEFT_MOTOR_PWM, G.RIGHT_MOTOR_PWM):
            # Oldalanként külön try: az egyik láb hibája nem hagyhatja járni a másikat.
            try:
                self._lgpio.tx_pwm(self._h, pwm, self._cfg.pwm_frequency_hz, 0)
            except Exception:  # noqa: BLE001 — a megállás best-effort, de mindkét oldalra
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
        self._heading = heading
        self._turning = turning
        try:
            # SORREND: előbb az irány, aztán a PWM — fordítva a motor egy pillanatra a
            # KORÁBBI irányba indulna el.
            self._lgpio.gpio_write(self._h, G.LEFT_MOTOR_DIR, left_level)
            self._lgpio.gpio_write(self._h, G.RIGHT_MOTOR_DIR, right_level)
            pct = duty * 100.0
            self._lgpio.tx_pwm(self._h, G.LEFT_MOTOR_PWM, self._cfg.pwm_frequency_hz, pct)
            self._lgpio.tx_pwm(self._h, G.RIGHT_MOTOR_PWM, self._cfg.pwm_frequency_hz, pct)
            # Megszakítható alvás: a watchdog `stop()`-ja azonnal visszaadja a vezérlést.
            self._interrupt.wait(min(seconds, self._cfg.max_run_s))
        finally:
            self.stop()
