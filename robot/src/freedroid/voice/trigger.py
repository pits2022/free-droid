"""Trigger: EGY interfész, több forrás.

**Miért nem ébresztőszó** (a Teremtő döntése, 2026-08-26): az openWakeWord a Pi-n
uninstallálható (a `tflite-runtime`-nak nincs cp313 kereke), a "Szabi" pedig KÉT
szótag — ébresztőszónak eleve rossz, a téves riasztás ~3 szótag alatt romlik el.
Helyette fizikai trigger: egy 2,4 GHz-es prezenter-kattintó (HID-billentyűzet).

**Miért interfész, és nem közvetlenül az evdev:** a forrás cserélhető (kattintó ma,
telefon-POST vagy vezetékes GPIO-gomb holnap), a `run()` hurok pedig egy eseménysorból
olvas, és nem tudja, ki tette bele. Ez nem elvi tisztaság: aug. 31-ig nincs is kattintó,
tehát a hurok addig CSAK így fejleszthető és tesztelhető.

## Biztonság — ezt olvasd el, mielőtt evdev-forrást írsz

Egy 2,4 GHz-es HID-vevő **injektálható billentyűzet** (MouseJack-osztályú támadás). Két
külön kockázat, és csak az egyik védhető:

* **A robot félbeszakítása** — bárki elküldheti a két érvényes kódot, ez NEM védhető ki
  (bármely RF-es HID hamisítható). Hatása kellemetlen, nem veszélyes. Aki ezt is ki
  akarja zárni, vezetékes GPIO-gombot tegyen `ALLJ`-ra: ez az interfész ingyen viszi.
* **Parancsvégrehajtás a Pi-n** — ha az injektált leütés egy konzol-shellig eljut, az
  RCE. Ez VÉDHETŐ, és az evdev-forrásnak KÖTELESSÉGE megtenni:
    1. `EVIOCGRAB` (python-evdev: `device.grab()`) — kizárólagos lefoglalás, a leütés
       sehová máshová nem jut el;
    2. kód-FEHÉRLISTA — csak a leképezett kódok hatnak, minden más eldobva;
    3. üzemeltetés: ne legyen getty/autologin a fizikai konzolon.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from enum import Enum
from typing import Protocol

log = logging.getLogger(__name__)


class Esemeny(str, Enum):
    """Amit egy trigger-forrás küldhet. Szándékosan KETTŐ.

    Nem bővítendő ok nélkül: minden új esemény egy új ág a hurokban, és egy
    demó-robotnál a kevés, kiszámítható viselkedés többet ér a gazdagságnál.
    """

    FIGYELJ = "figyelj"   # kezdj el hallgatni (push-to-talk)
    ALLJ = "allj"         # AZONNAL: mozgás és beszéd megszakítása


class TriggerSource(Protocol):
    """Egy esemény-forrás. A `start()` NEM blokkol: saját szálat indít, és a sorba tesz."""

    def start(self, sor: queue.Queue[Esemeny]) -> None: ...
    def close(self) -> None: ...


class BillentyuTrigger:
    """Billentyűzet-forrás: ENTER = FIGYELJ, `s` + ENTER = ALLJ.

    Ez a fejlesztői forrás, és aug. 31-ig (a kattintó megérkezéséig) az EGYETLEN. A
    demón nem ez megy, de a hurok szempontjából megkülönböztethetetlen a kattintótól —
    pont ezért lehet vele a teljes hurkot végigpróbálni hardver nélkül.

    A szál `daemon`: egy `input()`-on blokkoló szálat nem lehet kívülről felébreszteni,
    tehát a kilépést nem szabad rá bízni.
    """

    def __init__(self, folyam=None) -> None:
        self._folyam = folyam if folyam is not None else sys.stdin
        self._szal: threading.Thread | None = None
        self._all = threading.Event()

    def start(self, sor: queue.Queue[Esemeny]) -> None:
        self._szal = threading.Thread(target=self._olvas, args=(sor,), daemon=True)
        self._szal.start()

    def close(self) -> None:
        self._all.set()

    def _olvas(self, sor: queue.Queue[Esemeny]) -> None:
        while not self._all.is_set():
            sor_szoveg = self._folyam.readline()
            if not sor_szoveg:          # EOF: a bemenet elfogyott (pl. lezárt cső)
                return
            if self._all.is_set():
                return
            sor.put(Esemeny.ALLJ if sor_szoveg.strip().lower().startswith("s")
                    else Esemeny.FIGYELJ)


class TriggerBusz:
    """Több forrás, egy sor — és az ALLJ AZONNALI mellékhatása.

    A lényeg a `_azonnal`: az `ALLJ` nem várhatja meg, hogy a főszál a sorhoz érjen, mert
    a főszál épp BESZÉL vagy hosszú LLM-hívásban ül. A megszakítást ezért maga a busz
    végzi el, a forrás szálán, ABBAN a pillanatban — a sorba tett esemény már csak azt
    mondja meg a hurkinak, hogy a megkezdett kört dobja el.
    """

    def __init__(self, *forrasok: TriggerSource, azonnal=None) -> None:
        self._forrasok = forrasok
        self._azonnal = azonnal
        self._nyers: queue.Queue[Esemeny] = queue.Queue()
        self._sor: queue.Queue[Esemeny] = queue.Queue()
        self._szal: threading.Thread | None = None
        self._all = threading.Event()
        self.allj = threading.Event()

    def start(self) -> None:
        for forras in self._forrasok:
            forras.start(self._nyers)
        self._szal = threading.Thread(target=self._tovabbit, daemon=True)
        self._szal.start()

    def close(self) -> None:
        self._all.set()
        for forras in self._forrasok:
            forras.close()

    def var(self, timeout: float | None = None) -> Esemeny | None:
        """A következő esemény. `None`, ha letelt az idő."""
        try:
            return self._sor.get(timeout=timeout)
        except queue.Empty:
            return None

    def _tovabbit(self) -> None:
        while not self._all.is_set():
            try:
                esemeny = self._nyers.get(timeout=0.2)
            except queue.Empty:
                continue
            if esemeny is Esemeny.ALLJ:
                self.allj.set()
                if self._azonnal is not None:
                    # A megszakítás hibája NEM nyelheti el magát az eseményt: a hurok
                    # akkor is dobja el a kört, ha a motor-leállítás elhasalt — és a
                    # naplóban ott a nyom. Egy itt kirepülő kivétel megölné a
                    # továbbító szálat, azaz a TÖBBI gombnyomás is elveszne.
                    try:
                        self._azonnal()
                    except Exception:  # noqa: BLE001
                        log.exception("az ALLJ azonnali mellékhatása elhasalt")
            self._sor.put(esemeny)
