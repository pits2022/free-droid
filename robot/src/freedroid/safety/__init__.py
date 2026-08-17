"""Safety watchdog — the "reflex" layer.

Reads the HC-SR04 ultrasonic sensors on a SEPARATE thread and calls motion.stop()
the instant a RELEVANT sensor reads below threshold — without ever consulting the LLM.

Két döntés van beleöntve, mindkettő mérés/tapasztalat után, a specben (5. szakasz):

1. **min(3)** — egyetlen mérés terhelés alatt 73,5 cm-t is TÚLbecsülhet (`ranging.py`).
2. **IRÁNY-FÜGGŐ megállás** — egy fal a robot MÖGÖTT nem ok a megállásra előremenetben.
   A régi "bármelyik szenzor küszöb alatt -> stop" szabállyal a robot egy standon,
   háttal a falnak, meg sem tudna indulni.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable, Protocol

from freedroid.config import gpio as G
from freedroid.config.settings import load_settings
from freedroid.hw import open_gpiochip
from freedroid.motion.types import Direction
from freedroid.safety.ranging import measure_cm_min3

if TYPE_CHECKING:
    from freedroid.config.settings import Settings

log = logging.getLogger(__name__)

FRONT = "front"
REAR = "rear"


def relevant_sensors(heading: Direction | None, turning: bool = False) -> frozenset[str]:
    """Melyik szenzor állíthat meg ADOTT haladási irány mellett.

    | haladási irány | melyik szenzor állít meg |
    | előre          | front                    |
    | hátra          | rear                     |
    | helyben fordul | EGYIK SEM — ismert vak eset (lásd lent) |
    | áll / ismeretlen | MINDKETTŐ (fail-safe)  |

    A fordulás azért kivétel, és nem "mindkettő": helyben forduláskor a robot KÖZÉPPONTJA
    nem közeledik a falhoz, a súrolt ívet viszont egyik szenzor sem látja — tehát a
    megállás nem VÉDENE, csak megtiltaná a fordulást. Egy fal előtt álló robot így soha
    nem tudna elfordulni a faltól, és egy watchdog, ami mindig tilt, a demó előtti órában
    kerül kikapcsolásra. A vak ív a mechanika dolga (lökhárító), nem az ultrahangé.
    """
    if turning:
        return frozenset()
    if heading is Direction.FORWARD:
        return frozenset({FRONT})
    if heading is Direction.BACKWARD:
        return frozenset({REAR})
    return frozenset(G.ULTRASONIC)  # áll vagy ismeretlen -> a szigorúbb szabály


class Watchdog(Protocol):
    def start(self) -> None: ...
    def stop_monitoring(self) -> None: ...
    def distances_cm(self) -> dict[str, float | None]: ...
    def is_blocked(self) -> bool: ...


class UltrasonicWatchdog:
    """Threaded HC-SR04 watchdog (Pi-only, lgpio).

    `on_obstacle` a hívó megállítója (jellemzően `motion.stop`), és a szenzor-szálról
    hívjuk — legyen olcsó és újrahívható.

    `heading_source` a `motion` vezérlő állapotát adja vissza `(heading, is_turning)`
    alakban. Ha nincs megadva, minden mérés a fail-safe ágra esik (MINDKÉT szenzor
    állít meg): az alapértelmezés soha ne a megengedőbb legyen.
    """

    def __init__(self, on_obstacle: Callable[[], None],
                 settings: Settings | None = None,
                 heading_source: Callable[[], tuple[Direction | None, bool]] | None = None) -> None:
        import lgpio  # Pi-only, lusta import

        self._lgpio = lgpio
        self._cfg = (settings or load_settings()).safety
        self._on_obstacle = on_obstacle
        self._heading_source = heading_source or (lambda: (None, False))
        self._distances: dict[str, float | None] = dict.fromkeys(G.ULTRASONIC)
        self._blocked = False
        self._fault: str | None = None
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

        self._h = open_gpiochip()
        for sensor in G.ULTRASONIC.values():
            lgpio.gpio_claim_output(self._h, sensor["trig"], 0)
            lgpio.gpio_claim_input(self._h, sensor["echo"])

    def start(self) -> None:
        if self._thread is not None:
            return
        # daemon=True: a watchdog szál nem tarthatja életben a folyamatot kilépéskor.
        self._thread = threading.Thread(target=self._loop, name="freedroid-watchdog",
                                        daemon=True)
        self._stop_flag.clear()
        self._thread.start()

    def stop_monitoring(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def distances_cm(self) -> dict[str, float | None]:
        """A legutóbbi mérések. `inf` = szabad az út, `None` = NÉMA szenzor (hiba)."""
        return dict(self._distances)

    def is_blocked(self) -> bool:
        """Igaz, ha a LEGUTÓBBI kör akadályt talált a haladási irányban VAGY hibázott."""
        return self._blocked

    @property
    def fault(self) -> str | None:
        """A legutóbbi mérési kör hibája, ha volt — az egészség-ellenőrzésnek.

        Sikeres kör törli. Nem elég naplózni: egy hibázó watchdog kívülről pontosan
        úgy néz ki, mint egy jól működő, ha csak a `distances_cm()`-et nézzük.
        """
        return self._fault

    def close(self) -> None:
        self.stop_monitoring()
        try:
            self._lgpio.gpiochip_close(self._h)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    # --- belső ---

    def _threshold_cm(self, name: str) -> float:
        return self._cfg.per_sensor_cm.get(name, self._cfg.stop_threshold_cm)

    def _loop(self) -> None:
        while not self._stop_flag.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001 — a szál SEMMITŐL nem halhat meg
                # Egy kezeletlen kivétel itt CSENDBEN megszüntetné a védelmet: a szál
                # kilép, a robot megy tovább, és semmi nem jelzi. A fail-safe válasz
                # három részből áll, és mindhárom kell:
                #   1. megállítjuk a robotot (a hiba nem bizonyíték a szabad útra),
                #   2. LÁTHATÓVÁ tesszük (`fault` + `is_blocked`), mert egy naplóba
                #      írt kivétel ugyanolyan néma, mint a halott szál,
                #   3. és TOVÁBB MÉRÜNK — egy pillanatnyi lgpio hiba után magától
                #      visszaáll, egy tartós hiba pedig minden körben megállít.
                self._fault = repr(e)
                self._blocked = True
                log.exception("watchdog poll failed — fail-safe stop")
                try:
                    self._on_obstacle()
                except Exception:  # noqa: BLE001 — a megállító is hibázhat
                    log.exception("watchdog on_obstacle failed")
            self._stop_flag.wait(self._cfg.poll_interval_s)

    def poll_once(self) -> None:
        """Egy teljes mérési kör. Nyilvános, mert a szálon kívülről is kell:
        egészség-ellenőrzéshez és teszthez determinisztikus egy lépés kell."""
        heading, turning = self._heading_source()
        watched = relevant_sensors(heading, turning)

        blocked = False
        for name, pins in G.ULTRASONIC.items():
            # A nem figyelt szenzort MÉRJÜK, de nem állít meg: a `distances_cm()` így a
            # teljes képet mutatja (naplózás, "mi van körülöttem" kérdés), miközben a
            # megállítás szabálya irány-függő marad.
            cm = measure_cm_min3(self._lgpio, self._h, pins["trig"], pins["echo"])
            self._distances[name] = cm
            # A NÉMA szenzor (None) szándékosan akadály: egy meg sem szólaló szenzor nem
            # bizonyítja, hogy szabad az út — 2026-08-15-én pont egy szakadt föld-vezeték
            # némította el az elülsőt. Az `inf` (válaszolt, de üres a tér) NEM akadály.
            if name in watched and (cm is None or cm < self._threshold_cm(name)):
                blocked = True
                # AZONNAL, nem a kör végén. A `min(3)` miatt a másik szenzor bevárása
                # legrosszabb esetben 3 × 60 ms = 180 ms fékezési késleltetés lenne —
                # 25 cm-es küszöbnél ez elfogyasztja a teljes tartalékot. A ciklus
                # SZÁNDÉKOSAN nem szakad meg: a `distances_cm()` maradjon teljes.
                self._on_obstacle()

        self._blocked = blocked
        self._fault = None  # a kör végigfutott — a korábbi hiba elévült
