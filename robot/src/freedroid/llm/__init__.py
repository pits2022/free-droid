"""LLM kliens: felhő (WireGuard -> Ollama) elsődleges, edge (helyi Ollama) tartalék.

**A visszaesés SORRENDJE a spec „fallback-létrája": felhő -> edge -> safe mode.** A safe
mode nem itt van: ha MINDKÉT háttér elesik, ez a modul `LLMUnavailable`-t dob, és az
orchestrátor dönt (konzerv válasz, mozgás tiltva).

**Két időkorlát van, és a szétválasztásuk a modul lényege.**

A kézenfekvő megoldás — „adj a felhőnek 8 másodpercet, aztán essünk vissza" — MÉRHETŐEN
rossz, két külön okból:

1. **A felhő HIDEGEN 21 másodperc, mielőtt egy szót mondana** (mérve 2026-08-13: az első
   olvasat 18 tok/s-ot mutatott a 65 helyett — a modell betöltése). Egy rövid, közös
   korlát mellett az ELSŐ kérdés MINDIG időtúllépéssel esne vissza az edge-re, és onnan
   a robot a demó hátralévő részét a gyengébb 3B-vel beszélné végig. Ezért van
   `warmup()`, és ezért nem a generálási korlát dönt.
2. **A lassú felhő is jobb, mint az edge.** Ha a felhő ÉL, csak épp sokat gondolkodik, a
   3B-re váltás nem gyorsít, csak butít (a 8B az első demó-minőségű magyar persona).

Ezért a döntést egy **külön, rövid elérhetőség-próba** hozza meg (`/api/tags`, 2 s), és a
kiválasztott háttér utána **hosszú** generálási korlátot kap. A próba az, ami gyors —
nem a generálás.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Callable, Protocol

from freedroid.health.probe import http_get

if TYPE_CHECKING:
    from freedroid.config.settings import LLMEndpoints, Settings

log = logging.getLogger(__name__)


class Backend(str, Enum):
    CLOUD = "cloud"
    EDGE = "edge"


class LLMUnavailable(RuntimeError):
    """Egyik háttér sem felelt. Az orchestrátornak ez a safe mode kiváltó jele."""


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...
    def active_backend(self) -> Backend | None: ...


def _ollama_client(host: str, timeout: float):
    """Az `ollama` csomag kliense. Külön függvény, hogy teszt/mérés kicserélhesse."""
    import ollama  # lusta import: a csomag nehéz, és a hívási út enélkül is importálható

    return ollama.Client(host=host, timeout=timeout)


class FallbackLLMClient:
    """Felhő -> edge visszaesés. Kérésenként dönt, nem ragad be egy háttérbe.

    A háttér-választás KÉRÉSENKÉNT újra megtörténik: a WireGuard-alagút a demó közben
    is felállhat (vagy leeshet), és egy „egyszer edge, mindig edge" kliens a felállt
    alagutat sosem venné észre. A próba olcsó (egy helyi/alagúton belüli GET).
    """

    def __init__(self, settings: Settings | None = None,
                 client_factory: Callable[[str, float], object] | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg: LLMEndpoints = (settings or load_settings()).llm
        self._factory = client_factory or _ollama_client
        self._backend: Backend | None = None
        self._indok = ""

    # --- a hátterek leírása egy helyen ---

    def _params(self, backend: Backend) -> tuple[str, str, float]:
        """(url, modell, generálási időkorlát) az adott háttérhez."""
        c = self._cfg
        if backend is Backend.CLOUD:
            return c.cloud_url, c.cloud_model, c.cloud_timeout_s
        return c.edge_url, c.edge_model, c.edge_timeout_s

    def _probe(self, backend: Backend) -> tuple[bool, str]:
        """(elérhető-e, INDOK). Az indok azért jön vissza, mert a naplóban a
        „miért az edge felelt?" kérdés csak így válaszolható meg utólag."""
        url, _, _ = self._params(backend)
        code, _ = http_get(f"{url}/api/tags", timeout=self._cfg.probe_timeout_s)
        if code == 200:
            return True, "elérhető"
        if code == 0:
            return False, f"nem elérhető ({url}, {self._cfg.probe_timeout_s:g} s alatt)"
        return False, f"nem elérhető (HTTP {code}, {url})"

    def reachable(self, backend: Backend) -> bool:
        """Él-e az Ollama az adott oldalon. RÖVID korlát — ez a döntés, nem a generálás."""
        return self._probe(backend)[0]

    def active_backend(self) -> Backend | None:
        """A LEGUTÓBB sikeres háttér. `None`, amíg nem volt sikeres hívás."""
        return self._backend

    def active_model(self) -> str | None:
        """A LEGUTÓBB sikeres háttér MODELLNEVE — a naplóban a háttérnél többet mond:
        a „cloud" nem árulja el, hogy a v12-t vagy a nyers bázismodellt kérdeztük."""
        if self._backend is None:
            return None
        return self._params(self._backend)[1]

    def decision(self) -> str:
        """MIÉRT az a háttér felelt, ami. Teljes döntési nyom, egy sorban:

            "cloud: nem elérhető (http://10.0.0.1:11434, 2 s alatt) -> edge: felelt
             (szabi-3b-v12)"

        Ez az a mondat, amit fej nélküli Pi-n utólag olvasni akarunk. A háttér neve
        önmagában nem elég: abból nem derül ki, hogy a felhő HALOTT volt, vagy csak
        HIBÁZOTT — a kettő teljesen más javítást kíván.
        """
        return self._indok

    # --- generálás ---

    def generate(self, prompt: str) -> str:
        nyom: list[str] = []
        for backend in (Backend.CLOUD, Backend.EDGE):
            _, model, _ = self._params(backend)
            elerheto, indok = self._probe(backend)
            if not elerheto:
                # NAPLÓZVA, nem csak eldobva. Enélkül egy némán edge-re esett kör
                # semmilyen nyomot nem hagyna — és pont az a kör érdekes.
                nyom.append(f"{backend.value}: {indok}")
                # DEBUG, nem WARNING: a létra MŰKÖDÉSE nem rendellenesség, és az élő
                # menetben (2026-08-28) ez körönként egyszer sárgult be egy teljesen
                # normális állapotra — az a fajta figyelmeztetés, amit három perc után
                # már senki nem olvas el, és épp ezért a VALÓDIT is elrejti. Nem vész el
                # semmi: az összegző `LLM válasz:` sor ugyanezt az indokot INFO-n adja.
                log.debug("LLM háttér kihagyva — %s: %s", backend.value, indok)
                continue
            try:
                valasz = self._generate_on(backend, prompt)
            except Exception as e:  # noqa: BLE001 — bármi jön, a másik háttér a válasz
                nyom.append(f"{backend.value}: {self._magyarazat(backend, e)}")
                log.warning("LLM hívás sikertelen — %s: %s", backend.value, e)
                continue
            self._backend = backend
            nyom.append(f"{backend.value}: felelt ({model})")
            self._indok = " -> ".join(nyom)
            log.info("LLM válasz: %s", self._indok)
            return valasz
        self._indok = " -> ".join([*nyom, "safe mode"])
        # A safe mode kiváltója. Az OKOKAT visszük magunkkal: fej nélküli Pi-n a
        # "nem válaszolt" önmagában nem diagnózis.
        raise LLMUnavailable("egyik LLM háttér sem felelt — " + "; ".join(nyom))

    def _generate_on(self, backend: Backend, prompt: str) -> str:
        url, model, timeout = self._params(backend)
        kliens = self._factory(url, timeout)
        valasz = kliens.generate(model=model, prompt=prompt, stream=False)
        # A rendszerprompt a Modelfile-ban van beégetve (lásd training/Modelfile), tehát
        # itt CSAK a kérdés (vagy RAG módban a groundolt prompt) megy.
        return (self._szoveg(valasz) or "").strip()

    @staticmethod
    def _szoveg(valasz: object) -> str:
        """Az `ollama` csomag válasz-objektuma és a nyers dict is előfordul."""
        if isinstance(valasz, dict):
            return valasz.get("response", "")
        return getattr(valasz, "response", "") or ""

    def _magyarazat(self, backend: Backend, e: Exception) -> str:
        """Hibaüzenet, ami a fej nélküli Pi naplójában is elég a javításhoz."""
        _, model, _ = self._params(backend)
        if getattr(e, "status_code", None) == 404:
            # A javító parancs a TÉNYLEGES terjesztési úthoz igazodik: a modellek
            # publikus ollama.com modellek, tehát `pull` a javítás, nem `create`.
            return (f"a(z) '{model}' modell nincs betöltve — "
                    f"`ollama pull {model}`, ellenőrzés: `ollama list`")
        return f"{type(e).__name__}: {e}"

    # --- hidegindítás ---

    def warmup(self) -> Backend | None:
        """Betölteti a modellt, MIELŐTT az első kérdés elhangzik.

        A felhő hidegen 21 másodpercig tölt (mérve). Ez a csend a színpadon az első
        kérdésre esne, és a robot halottnak látszana. Egy egytokenes kérés kifizeti
        ezt a költséget indulásnál. Sosem dob: ha nem sikerül, a `generate()` úgyis
        dönt — a bemelegítés kényelem, nem előfeltétel.
        """
        for backend in (Backend.CLOUD, Backend.EDGE):
            if not self.reachable(backend):
                continue
            url, model, timeout = self._params(backend)
            try:
                kliens = self._factory(url, timeout)
                # `keep_alive`: a modell maradjon a memóriában a demó alatt. Enélkül az
                # Ollama 5 perc tétlenség után kiüríti, és a hidegindítás visszatér —
                # egy közönség-kérdések közti szünet pont ennyi.
                kliens.generate(model=model, prompt="szia", stream=False,
                                options={"num_predict": 1}, keep_alive="30m")
            except Exception as e:  # noqa: BLE001 — a bemelegítés sosem buktathat indulást
                log.warning("%s bemelegítés sikertelen: %s", backend.value, e)
                continue
            log.info("%s bemelegítve (%s)", backend.value, model)
            return backend
        return None


__all__ = ["Backend", "FallbackLLMClient", "LLMClient", "LLMUnavailable"]
