"""WS2812 státusz-gyűrű: MIT csinál a robot, 5 méterről, színtévesztőnek is.

A Teremtő döntése (2026-09-03, spec §6): kevés állapot, a MINTA legalább annyit mond,
mint a szín, a piros EGYET jelent. A fő sor a szuverenitás-demó láthatóvá tétele:
gondolkodás közben a gyűrű a FORRÁS színében forog — kék = felhő (8B a WireGuardon),
lila = edge (3B a Pi-n). Kihúzod a kábelt, lilára vált, és mégis válaszol.

Húzó modell, nem horog-erdő: a rajzoló szál képkockánként MEGKÉRDEZI az orchestrátort
(`scene_fn()`), mi az aktuális jelenet — az orchestrátor állapotából, a watchdogból, a
motor irányából és az akku-őrből számolva. Két esemény van csak, ami magától megy:
az akadály-villanás (a szenzor-szálról) és a boot-szivárvány.

ponytail: a `frame()` tiszta függvény (idő -> pixelek), így hardver nélkül tesztelhető;
a hardver egyetlen `show(pixels)` hívás a `neopixel_spi`-n. LED-szám: `LedSettings.count`
(a gyűrű darabszáma MÉRENDŐ, ha rádugtad — `FREEDROID_LED_COUNT`).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]


class Pattern(str, Enum):
    OFF = "off"
    SOLID = "solid"
    BREATHE = "breathe"     # lassú lélegzés (3 s) — "élek, de NEM hallgatok"
    PULSE = "pulse"         # gyors pulzálás (0,6 s) — a mikrofon nyitva
    SPIN = "spin"           # körbefutó fej + csóva (1 fordulat/s) — gondolkodik
    CHASE = "chase"         # futófény a haladás irányába — mozog
    FLASH = "flash"         # 3 villanás 1 s alatt — akadály-reflex
    RAINBOW = "rainbow"     # egy söprés — boot OK


@dataclass(frozen=True)
class Scene:
    pattern: Pattern
    color: RGB = (0, 0, 0)
    direction: int = 1      # CHASE: +1 előre, -1 hátra


# A spec §6 színei. A "halvány fehér" nem külön szín: a BREATHE maga fojtja.
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (0, 80, 255)
PURPLE = (170, 0, 255)
ORANGE = (255, 90, 0)
RED = (255, 0, 0)
BLACK = (0, 0, 0)

SOURCE_COLOR = {"cloud": BLUE, "edge": PURPLE}   # ismeretlen forrás -> fehér

OFF = Scene(Pattern.OFF)
SAFE = Scene(Pattern.SOLID, RED)
OBSTACLE = Scene(Pattern.FLASH, RED)
BOOT_OK = Scene(Pattern.RAINBOW)


def _scale(c: RGB, k: float) -> RGB:
    k = max(0.0, min(1.0, k))
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def _hue(h: float) -> RGB:
    """0..1 -> RGB a színkörön (6 szektor), a szivárványhoz."""
    # `int(h)` sosem 6: a legnagyobb double 1 alatt ×6 = 5.999999999999999 (mérve a
    # PR #105 review-ra, az 1 alatti 1e6 legnagyobb double-re is). Nem kell `% 6`.
    h = h % 1.0 * 6
    i, f = int(h), h - int(h)
    q, t = int(255 * (1 - f)), int(255 * f)
    return [(255, t, 0), (q, 255, 0), (0, 255, t), (0, q, 255), (t, 0, 255), (255, 0, q)][i]


def frame(scene: Scene, t: float, n: int) -> list[RGB]:
    """Egy képkocka a `t` másodpercnél, `n` LED-re. TISZTA: ugyanaz a (jelenet, idő)
    ugyanazt a képet adja — ezért tesztelhető hardver nélkül."""
    p, c = scene.pattern, scene.color
    if p is Pattern.OFF or n <= 0:
        return [BLACK] * n
    if p is Pattern.SOLID:
        return [c] * n
    if p is Pattern.BREATHE:
        k = 0.08 + 0.27 * (1 + math.sin(2 * math.pi * t / 3.0)) / 2     # 8–35 %
        return [_scale(c, k)] * n
    if p is Pattern.PULSE:
        k = 0.15 + 0.85 * (1 + math.sin(2 * math.pi * t / 0.6)) / 2
        return [_scale(c, k)] * n
    if p is Pattern.SPIN:
        head = (t % 1.0) * n
        out = []
        for i in range(n):
            d = (head - i) % n                     # milyen messze van a fej MÖGÖTT
            out.append(_scale(c, max(0.0, 1 - d / 4)))   # 4 pixeles csóva
        return out
    if p is Pattern.CHASE:
        head = int((t * 8) % n) * scene.direction
        return [c if ((i - head) % n) < 3 else _scale(c, 0.05) for i in range(n)]
    if p is Pattern.FLASH:
        on = (t % 0.33) < 0.15                     # 3 villanás / s
        return [c if on else BLACK] * n
    if p is Pattern.RAINBOW:
        return [_hue(i / n + t / 2.0) for i in range(n)]
    raise ValueError(p)


class Ring(Protocol):
    """A hardver: egy képkocka kirakása."""

    def show(self, pixels: list[RGB]) -> None: ...

    def close(self) -> None: ...


class NullRing:
    """Nincs gyűrű (Pi nélkül, vagy nincs rádugva): a képkockák a földre esnek, de a
    robot többi része ugyanúgy megy."""

    def show(self, pixels: list[RGB]) -> None:
        pass

    def close(self) -> None:
        pass


class NeoPixelRing:
    """WS2812 az SPI0-n (`/dev/spidev0.0`, GPIO10) az `adafruit-circuitpython-neopixel-spi`
    csomaggal. Az import LUSTA: a `board` modul Pi nélkül nem importálható."""

    def __init__(self, count: int, brightness: float) -> None:
        import board                                     # noqa: PLC0415
        import neopixel_spi                              # noqa: PLC0415
        self._px = neopixel_spi.NeoPixel_SPI(board.SPI(), count, brightness=brightness,
                                             auto_write=False)

    def show(self, pixels: list[RGB]) -> None:
        for i, p in enumerate(pixels):
            self._px[i] = p
        self._px.show()

    def close(self) -> None:
        self._px.fill(BLACK)
        self._px.show()


class LedController:
    """Rajzoló szál: `fps`-szer másodpercenként `scene_fn()` -> `frame()` -> `ring.show()`.

    `play(scene, seconds)` egy ÁTMENETI jelenet, ami ennyi ideig felülírja a húzottat —
    az akadály-villanás és a boot-szivárvány. Szálbiztos: az akadály a szenzor-szálról jön.
    A szál `daemon`: a gyűrű nem tarthatja fel a leállást; a `close()` lekapcsolja.
    """

    def __init__(self, ring: Ring, scene_fn: Callable[[], Scene], count: int,
                 fps: float = 30.0) -> None:
        self._ring, self._scene_fn, self._n, self._fps = ring, scene_fn, count, fps
        self._lock = threading.Lock()
        self._override: tuple[Scene, float] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="led")
        self._thread.start()

    def play(self, scene: Scene, seconds: float) -> None:
        with self._lock:
            self._override = (scene, time.monotonic() + seconds)

    def current(self, now: float | None = None) -> Scene:
        """Az éppen érvényes jelenet (az átmeneti nyer, amíg tart). Külön, hogy tesztelhető."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._override is not None:
                scene, until = self._override
                if now < until:
                    return scene
                self._override = None
        try:
            return self._scene_fn()
        except Exception:  # noqa: BLE001 — egy hibás jelenet ne ölje meg a rajzoló szálat
            log.exception("a LED-jelenet kiszámítása elhasalt")
            return OFF

    def _loop(self) -> None:
        t0 = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                self._ring.show(frame(self.current(now), now - t0, self._n))
            except Exception:  # noqa: BLE001
                log.exception("a LED-gyűrű írása elhasalt — a gyűrű innentől néma")
                return
            self._stop.wait(1.0 / self._fps)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            self._ring.close()
        except Exception:  # noqa: BLE001
            log.exception("a LED-gyűrű lekapcsolása elhasalt")


def build_ring(count: int, brightness: float) -> Ring:
    """Valódi gyűrű, ha van; különben `NullRing`, HANGOSAN. Egy hiányzó gyűrű ne
    akadályozza a demót — de ne is legyen néma rejtély, miért sötét."""
    try:
        return NeoPixelRing(count, brightness)
    except Exception as e:  # noqa: BLE001 — ImportError, OSError (nincs spidev), bármi
        log.warning("LED-gyűrű nem elérhető (%s) — a státuszfény kimarad", e)
        return NullRing()
