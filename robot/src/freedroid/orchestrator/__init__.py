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
from freedroid.voice.trigger import Esemeny

if TYPE_CHECKING:
    from freedroid.camera import CameraController
    from freedroid.config.settings import Settings
    from freedroid.llm import LLMClient
    from freedroid.motion import MotionController
    from freedroid.rag.retriever import Hit
    from freedroid.safety import Watchdog
    from freedroid.voice import STT, TTS, VAD
    from freedroid.voice.trigger import TriggerBusz

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

# Milyen sűrűn ébred a hurok, ha nincs esemény. Csak a LEÁLLÁS válaszidejét szabja meg
# (a gombnyomás ettől függetlenül azonnal érkezik) — a leállásé viszont a felső korlát:
# ennyi ideig tart legrosszabb esetben, mire a `systemctl stop` átmegy.
HUROK_EBREDES_S = 0.5


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
                 llm: LLMClient | None = None,
                 stt: STT | None = None,
                 tts: TTS | None = None,
                 vad: VAD | None = None,
                 trigger: TriggerBusz | None = None) -> None:
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
        # A hang-elemek LUSTÁN épülnek (`_hang()`): a konstruktoruk binárist és modellt
        # keres, az `ask_smoke.py` és a tesztek viszont hang nélkül futnak. Egy hiányzó
        # `piper` nem akadályozhatja meg a lánc többi részének a próbáját.
        self._stt, self._tts, self._vad = stt, tts, vad
        self._trigger = trigger
        # Diagnosztika: a távoli konzol (telefon) ezt fogja kiolvasni — "épp mit csinál?"
        self.state = State.LISTENING

    def _hang(self) -> tuple[STT, TTS, VAD, TriggerBusz]:
        """A hang-lánc + a trigger, első használatkor megépítve."""
        from freedroid.voice import EnergyVAD, FallbackSTT, PiperTTS
        from freedroid.voice.trigger import BillentyuTrigger, TriggerBusz

        if self._stt is None:
            self._stt = FallbackSTT(self._settings)
        if self._tts is None:
            self._tts = PiperTTS(self._settings)
        if self._vad is None:
            self._vad = EnergyVAD(self._settings)
        if self._trigger is None:
            self._trigger = TriggerBusz(BillentyuTrigger(), azonnal=self._azonnali_allj)
        return self._stt, self._tts, self._vad, self._trigger

    def _azonnali_allj(self) -> None:
        """Az ALLJ AZONNALI mellékhatása — a trigger szálán fut, nem a hurokban.

        Ez a lényege az egésznek: a főszál épp BESZÉL (a `speak()` blokkol) vagy egy
        LLM-hívásban ül, tehát ha a megállítás a hurok következő fordulójára várna, a
        gomb csak mondathatáron hatna. Egy csak mondathatáron ható vészstop pedig a
        gyakorlatban nincs.

        A sorrend szándékos: ELŐBB a motor. A beszéd elhallgattatása kellemetlenség
        kérdése, a mozgásé fizikai.
        """
        try:
            self.motion.stop()
        except Exception:  # noqa: BLE001 — a beszédet ettől még el kell hallgattatni
            log.exception("az ALLJ motor-leállítása elhasalt")
        megszakit = getattr(self._tts, "abort", None)
        if megszakit is not None:
            megszakit()

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
        """A fő hurok: trigger -> felvétel -> STT -> `ask()` -> beszéd. Push-to-talk.

        **"Ne hallja a saját hangját" — ez itt INGYEN megvan, nem külön mechanizmus.**
        A felvétel CSAK a FIGYELJ után indul, tehát beszéd közben soha nem hallgat. Egy
        ébresztőszavas hurokban ez valódi probléma lenne (a saját mikrofonunk mérve
        HALLJA a saját hangszórónkat: 8447-es csúcs/medián a hurok-teszten), és VAD-
        szüneteltetést kívánna. A fizikai trigger ezt a problémát megszünteti, nem
        megoldja — ez a döntés egyik nem szándékolt haszna.

        **A hurok SOHA nem hal meg egy hibás körtől.** Egy elszállt STT, egy néma felhő
        vagy egy beragadt hangeszköz egyetlen kört visz el; a robot mond valamit és
        várja a következő gombnyomást. A néma, kilépett folyamat a színpadon
        visszahozhatatlan — egy elrontott válasz nem az.
        """
        stt, tts, vad, trigger = self._hang()
        self.state = State.LISTENING
        self.start()
        trigger.start()
        try:
            while True:
                # `to_thread`, mert a lánc minden eleme BLOKKOLÓ (felvétel, subprocess,
                # HTTP). Enélkül egy `async` hurok látszana, ami valójában végig fogja
                # az eseményhurkot — és a jövőbeli második forrás (telefon-POST) sosem
                # jutna szóhoz.
                #
                # 🔴 IDŐKORLÁTTAL, és ez NEM finomhangolás. Egy `to_thread`-be zárt,
                # határidő nélküli `queue.get()`-et a megszakítás NEM tudja felébreszteni:
                # a korutin megkapja a CancelledError-t, a SZÁL viszont örökre ott marad,
                # és az `asyncio.run()` a kilépéskor a szálra vár — vagyis a robot a
                # `systemctl stop`-ra beragadna, és SIGKILL zárná le, lezáratlan
                # motorvezérlővel. (Egy teszt fogta meg: beragadt, nem bukott.)
                esemeny = await asyncio.to_thread(trigger.var, HUROK_EBREDES_S)
                if esemeny is None:
                    continue
                trigger.allj.clear()
                if esemeny is not Esemeny.FIGYELJ:
                    continue
                await asyncio.to_thread(self._egy_kor, stt, tts, vad, trigger)
        except KeyboardInterrupt:
            log.info("leállítás (Ctrl-C)")
        finally:
            # A lezárás MINDEN kilépési úton lefut, a megszakításon is: járó lánctalpak
            # egy kilépő folyamat után a legrosszabb kimenet.
            trigger.close()
            self.close()
        # A `CancelledError` SZÁNDÉKOSAN nincs elkapva: elnyelve a hívó nem tudná meg,
        # hogy a megszakítás megtörtént-e (`await feladat` némán `None`-t adna), és ez a
        # megszakítás-szemantika csendes elrontása. A takarítást a `finally` végzi, a
        # jelzést a kivétel — a kettő nem ugyanaz a feladat.

    def _egy_kor(self, stt: STT, tts: TTS, vad: VAD, trigger: TriggerBusz) -> None:
        """EGY kör, hibáival együtt. Külön metódus, mert így tesztelhető a hurok nélkül.

        Az `allj` jelzőt SZAKASZHATÁRONKÉNT nézzük. Nem finomabban: a megszakítás valódi
        munkáját (motor, beszéd) a trigger szála már elvégezte abban a pillanatban — ez a
        jelző csak azt mondja meg, hogy a MEGKEZDETT kört ne fejezzük be. Egy már
        elhangzott gombnyomás után nincs értelme sem az LLM-et megkérdezni, sem kimondani
        a választ.
        """
        try:
            self.state = State.THINKING
            # ponytail: a FELVÉTEL nem megszakítható. Az ALLJ-nak a mozgás (veszélyes) és
            # a beszéd (bosszantó) kell; egy futó felvétel egyik sem — legrosszabb esetben
            # pár másodperc kárba vész, aztán a jelző eldobja a kört. Ha kell:
            # egy threading.Event az EnergyVAD olvasó ciklusában, ~3 sor.
            hang = vad.record_until_silence()
            if trigger.allj.is_set():
                return
            szoveg = stt.transcribe(hang).strip()
            if not szoveg:
                log.info("üres átirat — nem kérdezünk, nem beszélünk")
                return
            log.info("átirat: %r", szoveg)
            if trigger.allj.is_set():
                return
            valasz = self.ask(szoveg)
        except Exception:  # noqa: BLE001 — egy hibás kör nem viheti el a hurkot
            log.exception("a kör elhasalt a válasz ELŐTT")
            valasz = SAFE_MODE_VALASZ
        if trigger.allj.is_set():
            return
        try:
            self.state = State.SPEAKING
            tts.speak(valasz)
        except Exception:  # noqa: BLE001 — a beszéd hibáját nem tudjuk kimondani
            log.exception("a beszéd elhasalt")
        finally:
            self.state = State.LISTENING


def main() -> None:
    """Console entry point (`freedroid`)."""
    try:
        asyncio.run(Orchestrator().run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Rendes leállás, nem hiba: a `run()` `finally`-ja már lezárta a hardvert. A
        # systemd `stop`-ja és a Ctrl-C is ide fut be, és egyik sem érdemel tracebacket.
        log.info("free-droid leállt")


__all__ = ["Orchestrator", "State", "MOZGATO_TOOLOK", "BIZTONSAGI_ELHARITAS"]
