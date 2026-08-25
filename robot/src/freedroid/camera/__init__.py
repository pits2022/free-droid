"""Camera pan/tilt control — MG996R servos on the PCA9685 (distinct from the
track motors in `motion`). Driven by the `camera(...)` tool.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from freedroid.config import gpio as G
from freedroid.config.settings import CameraSettings, load_settings

if TYPE_CHECKING:
    from freedroid.config.settings import Settings

log = logging.getLogger(__name__)


class CameraAction(str, Enum):
    """`camera(action=...)` — composite gestures."""
    FACE_SPEAKER = "face_speaker"
    NOD = "nod"
    SCAN = "scan"


class CameraController(Protocol):
    """Pan/tilt + named gestures. Mirrors the camera tool grammar."""

    def pan(self, direction: str, degrees: float) -> None: ...
    def tilt(self, direction: str, degrees: float) -> None: ...
    def action(self, action: CameraAction) -> None: ...


# --- geometria: tiszta függvények, hardver nélkül is mérhetők -----------------------
#
# Azért állnak KÍVÜL az osztályon, mert ez az egyetlen része a modulnak, ami off-Pi is
# ellenőrizhető — a többi az I2C-buszon dől el. A vágás SZÖGBEN történik, nem pulzusban,
# és ez nem stílus kérdése: ha csak a pulzust vágnánk, a nyilvántartott szög elszállna a
# fizikai határon túlra (három „balra 45" után 135 fokot hinne), és a következő
# „jobbra 10" NEM mozdítaná meg a kamerát, mert még mindig a határon kívül volna. A
# robot ilyenkor néma és mozdulatlan — a legrosszabb hibafajta a színpadon.


@dataclass(frozen=True)
class Tengely:
    """Egy tengely kalibrációja. Azért külön típus, mert a két tengely MÉRHETŐEN
    különbözik (2026-08-25: 0,0133 vs 0,0168 ms/fok, más közép, más holtjáték) — egy
    közös értékkészlet az egyikre biztosan hazudna."""

    nev: str
    csatorna: int
    centre_ms: float
    ms_per_deg: float
    min_ms: float
    max_ms: float
    backlash_deg: float


def tengelyek(cfg: CameraSettings) -> tuple[Tengely, Tengely]:
    """(pan, tilt) — a lapos, env-felülírható configból tengely-objektumok."""
    return (
        Tengely("pan", G.PAN_CHANNEL, cfg.pan_centre_ms, cfg.pan_ms_per_deg,
                cfg.min_ms, cfg.max_ms, cfg.pan_backlash_deg),
        Tengely("tilt", G.TILT_CHANNEL, cfg.tilt_centre_ms, cfg.tilt_ms_per_deg,
                cfg.min_ms, cfg.max_ms, cfg.tilt_backlash_deg),
    )


def szog_hatarok(t: Tengely) -> tuple[float, float]:
    """A biztonsági pulzus-sávnak megfelelő szögtartomány, a középhez képest.

    ASZIMMETRIKUS lehet, és a valóságban az is: a pan közepe 1,65 ms a 0,60-2,40-es
    sávban, tehát lefelé több hely van, mint fölfelé.
    """
    return ((t.min_ms - t.centre_ms) / t.ms_per_deg,
            (t.max_ms - t.centre_ms) / t.ms_per_deg)


def vagott_szog(t: Tengely, szog: float) -> float:
    also, felso = szog_hatarok(t)
    return min(max(szog, also), felso)


def lepesekre(fok: float, lepes: float) -> list[float]:
    """Egy elmozdulást egyenlő-ish lépésekre bont, az ÖSSZEG pontos megtartásával.

    A szervónak nincs sebesség-bemenete: egy nagy lépésre teljes gyorsasággal odaugrik.
    A lassú, folyamatos pásztázás CSAK így áll elő. Az összeg pontossága nem
    kozmetika — a gesztus végén a kamerának oda kell visszaállnia, ahonnan indult, és
    egy lebegőpontos maradék minden pásztázásnál elcsúsztatná.
    """
    # A NULLA/NEGATÍV lépésköz nem védhető ki csendben (PR #94 review). Nullánál
    # ZeroDivisionError jönne; negatívnál viszont a `max(1, ...)` miatt EGYETLEN nagy
    # lépés lenne — a szervó odaugrana, néma no-opként megszüntetve pont a lassú
    # pásztázást, amiért ez a függvény létezik. A javasolt `return []` szintén néma
    # (nem mozdul, és nem mondja meg, miért), ezért itt kivétel a helyes válasz.
    if lepes <= 0:
        raise ValueError(f"a lépésköz > 0 kell legyen, kapott: {lepes!r}")
    if fok <= 0:
        return []
    darab = max(1, math.ceil(fok / lepes))
    return [fok / darab] * darab


def pulzus_ms(t: Tengely, szog: float) -> float:
    """Szög (a középhez képest) -> pulzushossz. A vágás a hívó dolga."""
    return t.centre_ms + szog * t.ms_per_deg


class PanTiltCamera:
    """PCA9685-backed implementation (Pi-only).

    A parancsok RELATÍVAK (`camera pan left 45` = fordulj 45 fokkal balra), tehát az
    osztály nyilvántartja az aktuális szöget. Szervón nincs visszacsatolás, ezért a
    nyilvántartás csak akkor igaz, ha ismert helyzetből indul: a konstruktor emiatt
    KÖZÉPRE ÁLLÍTJA mindkét tengelyt. E nélkül az első `pan` egy ismeretlen
    kiindulóponthoz képest mozogna, és a szoftver mást hinne, mint ami a valóság.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        # Pi-only, ezért lusta import: a csomag off-Pi is importálható.
        import board
        import busio
        from adafruit_pca9685 import PCA9685

        self._cfg: CameraSettings = (settings or load_settings()).camera
        self._pan_t, self._tilt_t = tengelyek(self._cfg)
        self._keret_ms = 1000.0 / self._cfg.pwm_frequency_hz
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._pca = PCA9685(self._i2c, address=G.PCA9685_ADDR)
        self._pca.frequency = self._cfg.pwm_frequency_hz
        self._szog = {"pan": 0.0, "tilt": 0.0}
        for t in (self._pan_t, self._tilt_t):
            self._kiad(t, 0.0)

    # --- alacsony szint ---

    def _kiad(self, t: Tengely, szog: float) -> None:
        ms = pulzus_ms(t, szog)
        # A 12 bites regisztert a könyvtár 16 bites `duty_cycle`-ből számolja (16-tal
        # oszt), ezért megy ide a 0xFFFF és nem a 0x0FFF.
        self._pca.channels[t.csatorna].duty_cycle = int(ms / self._keret_ms * 0xFFFF)

    def _mozgat(self, t: Tengely, delta: float) -> None:
        cel = self._szog[t.nev] + delta
        vagott = vagott_szog(t, cel)
        if vagott != cel:
            # NEM kivétel: a "nézz még balrább" a demón álljon meg szépen a végállásnál.
            # De nem is néma: e nélkül a "nem fordult tovább" megkülönböztethetetlen
            # volna egy döglött szervótól.
            log.warning("%s: %.1f fok a határon kívül, vágva %.1f fokra "
                        "(sáv: %.2f..%.2f ms)", t.nev, cel, vagott, t.min_ms, t.max_ms)
        self._kiad(t, vagott)
        self._szog[t.nev] = vagott

    def _beall_holtjatek_nelkul(self, t: Tengely, szog: float) -> None:
        """Egy pozíció felvétele MINDIG ugyanabból az irányból közelítve.

        MÉRVE 2026-08-25: a fogaskerekek hézaga a panon 10, a tilten 5 fok — vagyis
        ugyanaz a pulzus 10 fokkal máshová visz, ha a másik irányból érkezel. Ez okozta,
        hogy a gesztusok után a kamera nem pontosan a kiindulóba tért vissza; a szoftver
        végig a HELYES pulzust adta ki, tehát szoftveresen ez nem is volt javítható.

        Az ellenszer a szokásos: alálövünk a holtjátéknyit, majd onnan érkezünk a
        célra — így a fogak mindig ugyanabból az irányból feszülnek egymásnak. Csak a
        gesztusok ZÁRÓ mozdulatára használjuk: egy sima `pan left 30` amúgy is relatív
        és hozzávetőleges, ott a dupla mozdulat csak lassítana.
        """
        if t.backlash_deg > 0:
            self._kiad(t, vagott_szog(t, szog - t.backlash_deg))
            time.sleep(self._cfg.step_s)
        self._kiad(t, szog)
        self._szog[t.nev] = szog

    @staticmethod
    def _elojel(irany: str, parok: dict[str, int], tengely: str) -> int:
        try:
            return parok[irany]
        except KeyError:
            raise ValueError(f"{tengely}: ismeretlen irány {irany!r} "
                             f"(várt: {', '.join(sorted(parok))})") from None

    # --- vezérlés ---

    def pan(self, direction: str, degrees: float) -> None:
        elojel = self._elojel(direction,
                              {"left": G.PAN_LEFT_SIGN, "right": -G.PAN_LEFT_SIGN}, "pan")
        self._mozgat(self._pan_t, elojel * degrees)

    def tilt(self, direction: str, degrees: float) -> None:
        elojel = self._elojel(direction,
                              {"up": G.TILT_UP_SIGN, "down": -G.TILT_UP_SIGN}, "tilt")
        self._mozgat(self._tilt_t, elojel * degrees)

    def action(self, action: CameraAction) -> None:
        if action is CameraAction.FACE_SPEAKER:
            # A hangforrás irányához mikrofontömb (DOA) kellene, a roboton EGY mikrofon
            # van. Hangosan bukik, nem néma no-op — ugyanaz az elv, mint a
            # `move(mode=approach_speaker)`-nél: egy csendben elnyelt tool-hívás a demón
            # úgy néz ki, mintha a robot nem értené a parancsot.
            raise NotImplementedError(
                f"camera action={action.value}: hangirány-becslés (DOA) kellene hozzá, "
                f"a roboton egy mikrofon van")

        # A gesztus a KIINDULÓ helyzethez képest mozog, és oda is tér vissza. A
        # visszaállítás `finally`-ben van, mert a fél úton félbeszakadt gesztus (kivétel
        # egy I2C-hibából) FERDÉN hagyná a kamerát — és a következő parancs onnan
        # számolna tovább.
        kezdo = dict(self._szog)
        try:
            if action is CameraAction.NOD:
                for _ in range(self._cfg.nod_count):
                    self._lepes(self.tilt, "down", self._cfg.nod_deg)
                    self._lepes(self.tilt, "up", self._cfg.nod_deg)
            else:  # SCAN — LASSAN pásztáz balról jobbra, majd vissza középre
                self._pasztaz("left", self._cfg.scan_deg)
                self._pasztaz("right", 2 * self._cfg.scan_deg)
                self._pasztaz("left", self._cfg.scan_deg)
        finally:
            # A NYILVÁNTARTOTT szög a mérvadó, nem a lépések összege: ha valamelyik
            # lépés a határba ütközött, az oda-vissza már nem egyenlíti ki magát.
            for t in (self._pan_t, self._tilt_t):
                self._beall_holtjatek_nelkul(t, kezdo[t.nev])

    def _lepes(self, mozdit, irany: str, fok: float) -> None:
        mozdit(irany, fok)
        time.sleep(self._cfg.step_s)

    def _pasztaz(self, irany: str, fok: float) -> None:
        """Lassú, folyamatos pásztázás — a kamerának LÁTNIA kell közben."""
        for reszlet in lepesekre(fok, self._cfg.scan_step_deg):
            self.pan(irany, reszlet)
            time.sleep(reszlet / self._cfg.scan_deg_per_s)

    def close(self) -> None:
        """Leállás: a szervók elengednek (a kamera lebillen). Ez a helyes kilépés —
        egy folyamat után tovább feszülő szervó órákig veszi az áramot."""
        self._pca.deinit()
        self._i2c.deinit()
