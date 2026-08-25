"""Fő hurok: ébresztőszó -> STT -> LLM -> TTS, a tool-ok párhuzamos végrehajtásával.

**Ami MA megvan (2026-08-18): a kérdéstől a motorokig tartó TELJES lánc, hang nélkül.**

    ask(kérdés) -> RAG -> LLM (felhő/edge) -> nyelvi őr -> guard() -> tool-ok -> beszéd

Ez billentyűzetről végigvihető, tehát a hangpipeline előtt is tesztelhető hardveren.
Az `execute()` a lánc alsó fele külön: egy KÉSZ válasz-szöveget hajt végre.

**Ami nincs: a hurok maga** (`run()`), mert a `voice/` még stub (ébresztőszó, STT, TTS).
Ezt szándékosan nem imitáljuk: egy félig megírt hurok, ami néma stubokat hív, zöld
tesztek mellett is működésképtelen robotot ad.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import TYPE_CHECKING

from freedroid.llm import FallbackLLMClient, LLMUnavailable
from freedroid.llm.language_guard import enforce_hungarian
from freedroid.motion import CytronMotionController
from freedroid.orchestrator import transcript
from freedroid.orchestrator.guard import GuardResult, guard
from freedroid.rag.context import build_prompt
from freedroid.safety import UltrasonicWatchdog
from freedroid.tools.handlers import ToolRegistry

if TYPE_CHECKING:
    from freedroid.camera import CameraController
    from freedroid.config.settings import Settings
    from freedroid.llm import LLMClient
    from freedroid.motion import MotionController
    from freedroid.rag.retriever import Hit
    from freedroid.safety import Watchdog

log = logging.getLogger(__name__)

# Amit egy hibás watchdog mellett NEM hajtunk végre. A `stop` szándékosan NINCS benne:
# megállni mindig szabad. A `camera` sem — a kamerát nem az ultrahang védi.
MOZGATO_TOOLOK = frozenset({"move", "turn"})

# Amit ilyenkor mond. Konzerv mondat, mert a modellt ilyenkor nem kérdezzük meg újra.
BIZTONSAGI_ELHARITAS = "Most nem mozdulok, Teremtőm. Nem látok tisztán."

# Safe mode: EGYIK elme sem felel. A második mondat szándékosan konkrét — egy
# szuverenitásról szóló előadáson az, hogy „se a felhő, se a helyi", maga az üzenet.
SAFE_MODE_VALASZ = ("Most nem tudok gondolkodni, Teremtőm. "
                    "Se a felhő, se a helyi elme nem felel.")

# Nyelvi újrapróbálkozás. A `language_guard` ezt a thunkot hívja, ha a modell kilépett
# a magyarból; ha a második kör sem magyar, konzerv mondat megy ki (CANNED_HU).
MAGYARUL = "Magyarul válaszolj!\n\n"


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
                 watchdog: Watchdog | None = None,
                 llm: LLMClient | None = None) -> None:
        self._settings = settings
        # A kliens konstruktora NEM nyúl a hálózathoz (a háttér-választás kérésenként
        # történik), tehát alapból megépíthető — Pi nélkül is.
        self.llm = llm or FallbackLLMClient(settings)
        self._retriever = None
        # Az UTOLSÓ `ask()` RAG-találatai. Diagnosztikai kimenet: e nélkül nem
        # dönthető el, hogy a válasz a korpuszból jött-e vagy a modellből — a
        # demó-modell pedig kifejezetten "v12 + RAG". Azért ITT áll és nem egy
        # második lekérdezésben (PR #93 review), mert így IGAZ MARAD akkor is, ha az
        # `ask()` valaha máshogy keresne: pontosan azt őrzi, amit a prompt kapott.
        self.utolso_talalatok: list[Hit] = []
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
        """A watchdog elindítása és a modell bemelegítése.

        KÜLÖN lépés a konstruktortól: egy félig megépült objektum ne indítson szálat,
        ami már meg is állíthatja a robotot.

        A bemelegítés is ide tartozik, és nem az első kérdéshez: a felhő HIDEGEN 21
        másodpercig tölti a modellt (mérve 2026-08-13), és az a csend a színpadon
        pont az első kérdésre esne.
        """
        self.watchdog.start()
        bemelegit = getattr(self.llm, "warmup", None)
        if bemelegit is not None:
            bemelegit()

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

    def ask(self, kerdes: str) -> str:
        """Egy teljes kör SZÖVEGBŐL: kérdés -> RAG -> LLM -> nyelvi őr -> tool-ok.

        Ez a lánc a hang nélkül is teljes, tehát billentyűzetről végigvihető. Ami
        hiányzik belőle, az kizárólag a `voice/` (ébresztőszó, STT, TTS).
        """
        hits = self.utolso_talalatok = self._talalatok(kerdes)
        prompt = build_prompt(kerdes, hits)
        esemeny = transcript.Interakcio(
            hallott=kerdes, prompt=prompt,
            rag_cimek=[h.chunk.title for h in hits])
        # MINDKÉT generálás a try-on BELÜL. A nyelvi őr ugyanis MÁSODSZOR is hívhatja a
        # modellt (ha az első válasz nem magyar), és a háttér a két hívás között is
        # eleshet — a `LLMUnavailable` akkor az `ask()`-ból kiszállna, magával rántva a
        # hurkot. Épp azt az egy dolgot rontaná el, amiért a safe mode létezik: hogy a
        # robot SOSE némuljon el. (PR #86 review.)
        try:
            nyers = self.llm.generate(prompt)
            hatter = self.llm.active_backend()
            esemeny.forras = hatter.value if hatter is not None else ""
            # A háttér neve önmagában nem diagnózis: a MODELL mondja meg, hogy a v12-t
            # vagy egy nyers bázismodellt kérdeztük, az INDOK pedig azt, miért arra esett.
            esemeny.modell = getattr(self.llm, "active_model", lambda: None)() or ""
            esemeny.hatter_indok = self._llm_indok()
            # A NYERS válasz azonnal az eseménybe: ha a nyelvi újrapróbálkozás bukik, a
            # napló akkor is megőrzi, MIT mondott a modell először. E nélkül pont a
            # legérdekesebb kör (idegen nyelvű válasz + eldőlt háttér) veszne el.
            esemeny.valasz = nyers
            # A nyelvi őr a `generate()` és a kimondás KÖZÉ ékelődik — ugyanaz az elv,
            # mint a biztonsági watchdognál: a szabály a kódban áll, nem a súlyokban.
            valasz = enforce_hungarian(
                nyers, regenerate=lambda: self.llm.generate(MAGYARUL + prompt))
        except LLMUnavailable as e:
            # NEM némulunk el: a safe mode konzerv mondata megy ki. Egy néma robot a
            # színpadon megkülönböztethetetlen a lefagyottól.
            esemeny.forras, esemeny.hiba = "safe", str(e)
            esemeny.hatter_indok = self._llm_indok()
            log.error("safe mode: %s", e)
            transcript.log(esemeny)
            return SAFE_MODE_VALASZ
        esemeny.valasz = valasz

        eredmeny = guard(valasz)
        esemeny.toolok = [t.name for t in eredmeny.toolok]
        transcript.log(esemeny)
        return self.execute_guarded(eredmeny)

    def _llm_indok(self) -> str:
        indok = getattr(self.llm, "decision", None)
        return indok() if indok is not None else ""

    def _talalatok(self, kerdes: str) -> list[Hit]:
        """RAG-találatok, vagy üres lista. A korpusz hiánya NEM némíthatja el a robotot:
        tények nélkül is tud beszélni, csak kevesebbet tud."""
        from freedroid.config.settings import load_settings

        cfg = (self._settings or load_settings()).rag
        if not cfg.enabled:
            return []
        if self._retriever is None:
            from freedroid.rag.corpus import load_corpus
            from freedroid.rag.retriever import Retriever
            try:
                chunks = (load_corpus(cfg.corpus_path) if cfg.corpus_path
                          else load_corpus())
            except OSError as e:
                log.error("a Yotengrit-korpusz nem tölthető be (%s) — RAG nélkül megyek", e)
                return []
            self._retriever = Retriever(chunks, title_boost=cfg.title_boost)
        return self._retriever.retrieve(kerdes, top_k=cfg.top_k,
                                        min_score=cfg.min_score,
                                        min_coverage=cfg.min_coverage)

    def execute(self, valasz: str) -> str:
        """A modell nyers válaszából: végrehajtjuk a tool-okat, visszaadjuk a KIMONDANDÓT.

        A hibák TARTALMAZVA vannak, de nem elnyelve: egy elbukó tool-hívás nem
        akadályozhatja meg, hogy a robot megszólaljon (a néma robot a színpadon
        halott robot), viszont a naplóba WARNING szinten bekerül. Ez nem "csendes
        hiba": a `dispatch` maga is naplóz, és a kitalált nevek a `guard`-on már
        kiestek — ide csak VALÓDI végrehajtási hiba juthat el.
        """
        return self.execute_guarded(guard(valasz))

    def execute_guarded(self, eredmeny: GuardResult) -> str:
        """Ugyanaz, de MÁR szétválasztott kimeneten — így az `ask()` egyszer őröl."""
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
        # Már CSAK a `voice/` hiányzik (ébresztőszó, STT, TTS):
        #   self.start()
        #   while True:
        #       await wake -> record -> transcribe
        #       speak(self.ask(atirat))
        raise NotImplementedError("Phase 4.2: a voice/ (wake/STT/TTS) kell a hurokhoz — "
                                  "a kérdéstől a motorokig tartó lánc az `ask()`-ban kész")


def main() -> None:
    """Console entry point (`freedroid`)."""
    asyncio.run(Orchestrator().run())


__all__ = ["Orchestrator", "State", "MOZGATO_TOOLOK", "BIZTONSAGI_ELHARITAS"]
