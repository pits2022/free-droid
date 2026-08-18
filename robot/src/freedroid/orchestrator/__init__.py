"""Fő hurok: ébresztőszó -> STT -> LLM -> TTS, a tool-ok párhuzamos végrehajtásával.

**Ami MA megvan (Phase 4.1, 2026-08-18): a VÉGREHAJTÁSI út.** A modell nyers válaszától
a motorokig — `guard()` (kimondható szöveg / végrehajtható tool-ok szétválasztása) ->
`ToolRegistry.dispatch`. Ez hardveren kipróbálható a hang és az LLM nélkül is: a
`freedroid.orchestrator.Orchestrator.execute()` egy KÉSZ válasz-szöveget kap.

**Ami nincs: a hurok maga** (`run()`), mert a `voice/` és az `llm/` még stub (Phase 4.2).
Ezt szándékosan nem imitáljuk: egy félig megírt hurok, ami néma stubokat hív, zöld
tesztek mellett is működésképtelen robotot ad.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import TYPE_CHECKING

from freedroid.motion import CytronMotionController
from freedroid.orchestrator.guard import GuardResult, guard
from freedroid.safety import UltrasonicWatchdog
from freedroid.tools.handlers import ToolRegistry

if TYPE_CHECKING:
    from freedroid.camera import CameraController
    from freedroid.config.settings import Settings
    from freedroid.motion import MotionController
    from freedroid.safety import Watchdog

log = logging.getLogger(__name__)

# Amit egy hibás watchdog mellett NEM hajtunk végre. A `stop` szándékosan NINCS benne:
# megállni mindig szabad. A `camera` sem — a kamerát nem az ultrahang védi.
MOZGATO_TOOLOK = frozenset({"move", "turn"})

# Amit ilyenkor mond. Konzerv mondat, mert a modellt ilyenkor nem kérdezzük meg újra.
BIZTONSAGI_ELHARITAS = "Most nem mozdulok, Teremtőm. Nem látok tisztán."


class State(str, Enum):
    LISTENING = "listening"   # waiting for wake word
    THINKING = "thinking"     # STT + LLM
    SPEAKING = "speaking"     # TTS + tool execution
    SAFE_MODE = "safe_mode"   # critical fault: motion disabled, canned replies


class Orchestrator:
    """Összekötő réteg. A vezérlők KÍVÜLRŐL is beadhatók (teszt, illetve Pi nélküli
    futtatás) — alapból a valódi hardvert építi meg.

    Bekötési sorrend (robot/README.md): config -> motion + safety -> tools -> llm -> voice.
    A watchdog azelőtt indul, hogy bármilyen mozgás lehetséges lenne.
    """

    def __init__(self, settings: Settings | None = None,
                 motion: MotionController | None = None,
                 camera: CameraController | None = None,
                 watchdog: Watchdog | None = None) -> None:
        self._settings = settings
        self.motion = motion or CytronMotionController(settings)
        self.camera = camera
        # A watchdog a `motion`-től olvassa a haladási irányt — EGYETLEN forrás, nem
        # vezet saját nyilvántartást (spec 5. szakasz).
        self.watchdog = watchdog or UltrasonicWatchdog(
            on_obstacle=self.motion.stop,
            settings=settings,
            heading_source=lambda: (self.motion.heading, self.motion.is_turning),
        )
        self.tools = ToolRegistry(motion=self.motion, camera=camera)

    def start(self) -> None:
        """A watchdog elindítása. KÜLÖN lépés a konstruktortól: egy félig megépült
        objektum ne indítson szálat, ami már meg is állíthatja a robotot."""
        self.watchdog.start()

    def close(self) -> None:
        # A watchdog leállítása is try alatt: ha a szál-join elhasal, a motorok
        # LEZÁRATLANUL maradnának — épp a legrosszabb kimenet (járó lánctalpak egy
        # kilépő folyamat után). A lezárás sorrendje szándékos (előbb a watchdog, hogy
        # ne állítson meg egy már lezárt vezérlőt), de egyik lépés sem előfeltétele a
        # másiknak.
        try:
            self.watchdog.stop_monitoring()
        except Exception:  # noqa: BLE001 — a vezérlők lezárása ettől nem maradhat el
            log.exception("watchdog leállítása sikertelen")
        for vezerlo in (self.motion, self.camera):
            zaras = getattr(vezerlo, "close", None)
            if zaras is not None:
                try:
                    zaras()
                except Exception:  # noqa: BLE001 — a másikat is le kell zárni
                    log.exception("vezérlő lezárása sikertelen: %r", vezerlo)

    def execute(self, valasz: str) -> str:
        """A modell nyers válaszából: végrehajtjuk a tool-okat, visszaadjuk a KIMONDANDÓT.

        A hibák TARTALMAZVA vannak, de nem elnyelve: egy elbukó tool-hívás nem
        akadályozhatja meg, hogy a robot megszólaljon (a néma robot a színpadon
        halott robot), viszont a naplóba WARNING szinten bekerül. Ez nem "csendes
        hiba": a `dispatch` maga is naplóz, és a kitalált nevek a `guard`-on már
        kiestek — ide csak VALÓDI végrehajtási hiba juthat el.
        """
        eredmeny = guard(valasz)

        # A tiltás ELŐRE dől el, az egész kötegre — nem menet közben. A menet közbeni
        # döntés SORRENDFÜGGŐ volt: a `[camera, move]` válasznál a kamera még lefutott,
        # a `[move, camera]`-nál nem, pedig a két válasz ugyanazt kéri. Egy kis modell
        # tool-sorrendje nem stabil, tehát ez futásonként változó viselkedés lett volna
        # — pont abban az állapotban, amikor a robot már nem lát tisztán.
        if self._mozgas_tiltott() and any(t.name in MOZGATO_TOOLOK
                                          for t in eredmeny.toolok):
            log.warning("mozgás letiltva (watchdog hiba), a köteg eldobva: %r",
                        [t.name for t in eredmeny.toolok])
            return BIZTONSAGI_ELHARITAS

        for tool in eredmeny.toolok:
            try:
                self.tools.dispatch(tool)
            except Exception:  # noqa: BLE001 — a beszéd fontosabb, mint a tool
                log.exception("tool-hívás sikertelen: %r %r", tool.name, tool.args)
        return eredmeny.beszed

    def guard_result(self, valasz: str) -> GuardResult:
        """A szétválasztás végrehajtás NÉLKÜL — naplózáshoz és szárazpróbához."""
        return guard(valasz)

    def _mozgas_tiltott(self) -> bool:
        """Igaz, ha a watchdog HIBÁS. Az `is_blocked` szándékosan NEM ok: az a
        normális "akadály van előttem" állapot, amit maga a watchdog kezel — abból
        letiltást csinálni azt jelentené, hogy a robot egy fal előtt soha többé nem
        indul el, még elfelé sem."""
        return getattr(self.watchdog, "fault", None) is not None

    async def run(self) -> None:
        # A hurok a `voice/` + `llm/` megvalósítására vár (Phase 4.2):
        #   self.start()
        #   while True:
        #       await wake -> record -> transcribe -> llm.generate
        #       speak(self.execute(valasz))
        raise NotImplementedError("Phase 4.2: voice/ + llm/ kell a hurokhoz "
                                  "(a végrehajtási út az `execute()`-ban már megvan)")


def main() -> None:
    """Console entry point (`freedroid`)."""
    asyncio.run(Orchestrator().run())


__all__ = ["Orchestrator", "State", "MOZGATO_TOOLOK", "BIZTONSAGI_ELHARITAS"]
