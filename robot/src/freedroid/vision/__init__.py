"""A felhős VLM kliense — Szabi szeme.

**A modul EGY szabálya: a látás bukása SOSEM viszi el a kört.** Minden hibaág `None`-t
ad (indokkal a naplóban), és az orchestrátor ebből építi a negatív `[LÁTVÁNY]` blokkot.

Ez SZÁNDÉKOS ELTÉRÉS a `CloudWhisperSTT`-től, ami dob: ott a hiba azt jelenti, hogy
nincs is kérdés (a robot némán állna), itt viszont a hiba egy túlélhető ÁLLAPOT, amit
a robot ki tud mondani — és ki is KELL mondania, mert a néma kihagyás pontosan az az
állapot, amiben a modell 2026-08-28-án konfabulált egy képleírást.

Nincs edge-ág: a látás csak felhős (spec §2). A 3B már így is a lassú ág.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Callable, Protocol

from freedroid.health.probe import http_get, jelold_elerhetetlennek, korben_elerhetetlen

if TYPE_CHECKING:
    from freedroid.config.settings import Settings, VisionSettings

log = logging.getLogger(__name__)


class VLMClient(Protocol):
    """A felhős VLM szűk felülete — ezt várja az `Orchestrator(vlm=...)` paramétere.
    Mirrors `CameraController`/`MotionController` (`camera/__init__.py`,
    `motion/__init__.py`): egy Protocol a teszt-dublőrökhöz is, nem csak a valódihoz."""

    def elerheto(self) -> tuple[bool, str]: ...
    def describe(self, jpeg: bytes) -> str | None: ...


def _ollama_client(host: str, timeout: float):
    """Az `ollama` csomag kliense — ugyanaz a seam, mint a `freedroid.llm`-ben."""
    import ollama  # noqa: PLC0415 — lusta import: a csomag nehéz

    return ollama.Client(host=host, timeout=timeout)


class CloudVLM:
    def __init__(self, settings: Settings | None = None,
                 client_factory: Callable[[str, float], object] | None = None) -> None:
        from freedroid.config.settings import load_settings  # noqa: PLC0415

        self._cfg: VisionSettings = (settings or load_settings()).vision
        self._factory = client_factory or _ollama_client

    def elerheto(self) -> tuple[bool, str]:
        """(él-e a VLM végpontja, INDOK). Az indok a naplóé: a „miért nem látott?"
        kérdés utólag csak így válaszolható meg."""
        if not self._cfg.enabled:
            return False, "a látás ki van kapcsolva (vision.enabled=False)"
        url = self._cfg.url
        # Egy körben egy várakozás: ha az STT vagy az LLM próbája már megbukott
        # ugyanezen a hoston, itt nem várunk ki még egy időkorlátot.
        if korben_elerhetetlen(url):
            return False, f"nem elérhető ({url}, a kör korábbi próbája szerint)"
        code, _ = http_get(f"{url}/api/tags", timeout=self._cfg.probe_timeout_s)
        if code == 200:
            return True, "elérhető"
        if code == 0:
            jelold_elerhetetlennek(url)
            return False, f"nem elérhető ({url}, {self._cfg.probe_timeout_s:g} s alatt)"
        return False, f"nem elérhető (HTTP {code}, {url})"

    def describe(self, jpeg: bytes) -> str | None:
        """A kép leírása, vagy `None`. SOSEM dob."""
        if not self._cfg.enabled or not jpeg:
            return None
        try:
            kliens = self._factory(self._cfg.url, self._cfg.timeout_s)
            valasz = kliens.generate(
                model=self._cfg.model,
                prompt=self._cfg.prompt,
                images=[base64.b64encode(jpeg).decode("ascii")],
                stream=False)
            # A válasz-kinyerés IS az őrzött ágban van: egy nem-sztring `response` mező
            # (pl. hibás VLM-kliens, ami számot ad vissza) a `.strip()`-en dobna, és a
            # modul EGYETLEN szabálya, hogy a `describe()` SOSEM dob — a kör akkor is
            # menjen tovább, ha a hiba a válasz FELDOLGOZÁSÁBAN van, nem a hívásban.
            szoveg = (valasz.get("response") if isinstance(valasz, dict)
                      else getattr(valasz, "response", "")) or ""
            szoveg = szoveg.strip()
        except Exception as e:  # noqa: BLE001 — hálózat/HTTP/időtúllépés/rossz válasz, mind ugyanaz
            # A KAPCSOLÓDÁSI hibát (OSError — ide tartozik a `TimeoutError` is) a
            # `korben_elerhetetlen` cache-be is beírjuk: eddig a `describe()` MEGTUDTA,
            # hogy a host halott, de nem szólt senkinek — a kör hátralévő része (egy
            # esetleges edge-STT/LLM próba) ugyanazt az időkorlátot várta volna ki
            # újra. Egy rossz VÁLASZALAK (pl. `AttributeError` a `.strip()`-en) NEM
            # kapcsolódási hiba — a host felelt, csak rosszul —, ezért az NEM jelöl.
            if isinstance(e, OSError):
                jelold_elerhetetlennek(self._cfg.url)
            log.warning("a felhős VLM nem válaszolt (%s: %s) — Szabi most nem lát",
                        type(e).__name__, e)
            return None
        if not szoveg:
            log.warning("a felhős VLM üres leírást adott — Szabi most nem lát")
            return None
        # A HOSSZ mehet INFO-ra, a SZÖVEG nem: ez egy hallgató LEÍRÁSA, a journald pedig
        # perzisztens és a demó előtti törlés (`find /var/log/freedroid -delete`) nem éri
        # el — ugyanaz a kapu, mint az STT-átiratnál (`orchestrator/__init__.py`).
        log.info("látvány kész: %d karakter", len(szoveg))
        log.debug("látvány: %r", szoveg)
        return szoveg


__all__ = ["CloudVLM"]
