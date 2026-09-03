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

import fcntl
import glob
import logging
import os
import queue
import struct
import sys
import threading
from enum import Enum
from pathlib import Path
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


def _esemeny(sor: str) -> Esemeny:
    """Egy beírt sor -> esemény. KÖZÖS, mert a két forrás nyelvtana nem csúszhat szét:
    ha a FIFO-ban az `s` mást jelentene, mint a billentyűzeten, az a legrosszabb fajta
    meglepetés — a STOP-é."""
    return Esemeny.ALLJ if sor.strip().lower().startswith("s") else Esemeny.FIGYELJ


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
            if not sor_szoveg:
                # EOF. SZOLGÁLTATÁSKÉNT ez a NORMÁLIS eset: a systemd alatt nincs stdin,
                # tehát ez a forrás azonnal elhallgat — egy fejetlen roboton úgysem
                # gépel senki. Azért naplózzuk, mert némán ez "a gomb nem működik"
                # rejtélyként jönne elő, amikor a kattintó megérkezik.
                log.info("billentyű-trigger: nincs bemenet (EOF), ez a forrás elhallgat")
                return
            if self._all.is_set():
                return
            sor.put(_esemeny(sor_szoveg))


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


class FifoTrigger:
    """Nevesített cső: `echo > /run/freedroid/trigger`. A SZOLGÁLTATÁS triggere.

    **Miért kellett (2026-08-28):** a hurok systemd alatt fut, ahol NINCS stdin — a
    billentyű-forrás azonnal elhallgat, tehát a robot felállt, bemelegített, és
    megszólíthatatlan volt. A kattintó csak aug. 31-én érkezik; addig ez az egyetlen út,
    és utána is megmarad TÁVOLI KONZOLNAK (a Teremtő telefonjáról SSH-n keresztül —
    a 2026-08-26-i „telefon másodlagos, de távoli konzolnak verhetetlen" döntés).

        echo    > /run/freedroid/trigger     # FIGYELJ
        echo s  > /run/freedroid/trigger     # ÁLLJ

    **`O_RDWR`, és ez nem trükközés — KÉT hibát kerül el, a súlyosabbik a nyitásnál van.**

    1. `O_RDONLY` mellett maga az `os.open()` BLOKKOL, amíg nem érkezik egy író. A
       `start()` tehát soha nem térne vissza, és vele az egész orchestrátor beragadna
       indulás közben. (Mutációval mérve 2026-08-28: a teszt nem bukott, hanem TIMEOUT-ra
       futott — pontosan ez a viselkedés.)
    2. És ha mégis megnyílna, a `read()` EOF-ot adna, amint az utolsó író elengedi — vagyis
       minden `echo` után újra kellene nyitni, és a két nyitás között érkező jelzés elveszne.

    `O_RDWR`-rel a folyamat maga marad író: a nyitás azonnal visszatér, EOF sosem jön, a
    `read()` egyszerűen a következő üzenetig blokkol. Linuxon ez definiált viselkedés.

    A jogosultság a folyamat umask-ja szerint alakul (mérve a Pi-n: `prw-r-----`, azaz a
    tulajdonos ír, a csoport olvas). Ez elég: a Teremtő `creator`-ként, azaz TULAJDONOSKÉNT
    ír bele. Nem is a robot biztonsági határa — aki a Pi-n `echo`-zni tud, az úgyis
    mindent tud.
    """

    def __init__(self, utvonal: str | Path = "/run/freedroid/trigger") -> None:
        self._ut = Path(utvonal)
        self._fd: int | None = None
        self._szal: threading.Thread | None = None
        self._all = threading.Event()

    def start(self, sor: queue.Queue[Esemeny]) -> None:
        try:
            if not self._ut.exists():
                os.mkfifo(self._ut, 0o660)
            self._fd = os.open(self._ut, os.O_RDWR)
        except OSError as e:
            # NEM végzetes: a robot a többi forrással működik tovább. De hangosan, mert
            # e nélkül a szolgáltatás megszólíthatatlan, és az némán "nem hallja" lenne.
            log.warning("a FIFO-trigger nem nyílt meg (%s): %s — a robot ezen az úton "
                        "NEM szólítható meg", self._ut, e)
            return
        self._szal = threading.Thread(target=self._olvas, args=(sor,), daemon=True)
        self._szal.start()
        log.info("FIFO-trigger él: echo > %s  (ÁLLJ: echo s > %s)", self._ut, self._ut)

    def close(self) -> None:
        self._all.set()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _olvas(self, sor: queue.Queue[Esemeny]) -> None:
        maradek = b""
        while not self._all.is_set():
            # A leírót HELYI változóba, mert a `close()` MÁS SZÁLON fut: a ciklus tetején
            # még nem áll az `_all` jelző, mire ideérünk, a `close()` lefuthat egészben,
            # és a `self._fd` `None` lesz. Az `os.read(None, ...)` `TypeError`-t dob, amit
            # az alábbi `except OSError` NEM fog el — vagyis a leállás egy elkapatlan
            # veremkiíratással végződne egy daemon szálban. (PR #100 review, 2. kör.)
            fd = self._fd
            if fd is None:
                return
            try:
                darab = os.read(fd, 4096)
            except OSError:
                return                      # lezárt leíró: rendes leállás
            if not darab:
                continue
            maradek += darab
            # SORONKÉNT, mert egy `echo` több sort is írhat, és két gyors jelzés
            # ugyanabban az olvasásban érkezhet — összevonva a második elveszne.
            while b"\n" in maradek:
                elso, maradek = maradek.split(b"\n", 1)
                sor.put(_esemeny(elso.decode("utf-8", "replace")))


# A kattintó gombjai -> esemény. Linux `input-event-codes.h` kódok. A KÓDOK MÉRENDŐK:
# a 2026-09-03-i Elan "Wireless Present" (04f3:1812) még nem lett lenyomva; az itt álló
# leképezés a szokásos prezenter-kiosztás (PageDown = következő dia, PageUp = előző,
# Esc/`b` = elsötétítés). Az ismeretlen kódot a naplóból olvasd ki, és ide írd be.
# A fehérlista NEM opcionális — lásd a modul biztonsági bekezdését.
KATTINTO_GOMBOK: dict[int, Esemeny] = {
    109: Esemeny.FIGYELJ,   # KEY_PAGEDOWN
    104: Esemeny.ALLJ,      # KEY_PAGEUP
    1: Esemeny.ALLJ,        # KEY_ESC
    48: Esemeny.ALLJ,       # KEY_B
}


class KattintoTrigger:
    """Prezenter-kattintó (HID-billentyűzet) az evdev-en, KÖNYVTÁR NÉLKÜL.

    ponytail: nincs python-evdev — egy C-kiterjesztés egy 24 bájtos struct olvasásáért.
    A `struct input_event` = `timeval` (2×long) + type (u16) + code (u16) + value (s32);
    a `struct.Struct("llHHi")` natív igazítással pont ezt adja 64 biten (a spec 64 bites
    Pi OS-t ír elő). Az `EVIOCGRAB` egy `ioctl`: `_IOW('E', 0x90, int)` = 0x40044590.

    A biztonsági kötelességek a modul docstringjéből: (1) kizárólagos lefoglalás, a
    leütés sehová máshova nem jut; (2) csak a `gombok` fehérlistája hat, minden más
    eldobva (naplózva, mert a kalibráláshoz pont az ismeretlen kód kell); (3) csak a
    LENYOMÁS (value == 1) számít — az ismétlés (2) egy lenyomva tartott gombból
    sorozat-FIGYELJ-et csinálna.

    A szál `daemon`, ugyanazért, mint a billentyűzeté: az `os.read` egy karakteres
    eszközön a következő eseményig blokkol, a `close()` nem ébreszti fel. Kilépéskor a
    folyamat viszi magával.
    """

    _REKORD = struct.Struct("llHHi")
    _EVIOCGRAB = 0x40044590
    _EV_KEY = 1

    def __init__(self, minta: str = "/dev/input/by-id/*Present*-event-kbd",
                 gombok: dict[int, Esemeny] | None = None) -> None:
        self._minta = minta
        self._gombok = gombok if gombok is not None else KATTINTO_GOMBOK
        self._fd: int | None = None
        self._szal: threading.Thread | None = None
        self._all = threading.Event()

    def start(self, sor: queue.Queue[Esemeny]) -> None:
        utak = sorted(glob.glob(self._minta))
        if not utak:
            # NEM végzetes (a FIFO és a billentyűzet marad), de hangos: e nélkül a
            # bedugott, de ismeretlen nevű kattintó némán "nem működne".
            log.warning("kattintó nem található (%s) — ezen az úton NEM szólítható meg",
                        self._minta)
            return
        try:
            self._fd = os.open(utak[0], os.O_RDONLY)
            fcntl.ioctl(self._fd, self._EVIOCGRAB, 1)
        except OSError as e:
            # A grab hibája is végzetes ERRE a forrásra: grab nélkül a leütés a konzolig
            # jut, ami a modul biztonsági bekezdése szerint tilos.
            log.warning("kattintó nem foglalható le (%s): %s", utak[0], e)
            self.close()
            return
        self._szal = threading.Thread(target=self._olvas, args=(sor,), daemon=True)
        self._szal.start()
        log.info("kattintó él: %s, gombok %s", utak[0], sorted(self._gombok))

    def close(self) -> None:
        self._all.set()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _olvas(self, sor: queue.Queue[Esemeny]) -> None:
        meret = self._REKORD.size
        while not self._all.is_set():
            fd = self._fd              # helyi másolat, mint a FIFO-nál: a close() más szálon fut
            if fd is None:
                return
            try:
                darab = os.read(fd, meret * 64)
            except OSError:
                return                 # lezárt leíró vagy kihúzott eszköz (ENODEV)
            if not darab:
                return                 # EOF: az eszköz eltűnt
            egesz = darab[:len(darab) - len(darab) % meret]
            for _, _, tipus, kod, ertek in self._REKORD.iter_unpack(egesz):
                if tipus != self._EV_KEY or ertek != 1:
                    continue
                esemeny = self._gombok.get(kod)
                if esemeny is None:
                    log.info("kattintó: ismeretlen gomb, kód %d (eldobva)", kod)
                    continue
                sor.put(esemeny)
