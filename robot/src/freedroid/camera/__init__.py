"""Camera pan/tilt control — MG996R servos on the PCA9685 (distinct from the
track motors in `motion`). Driven by the `camera(...)` tool.
"""

from __future__ import annotations

import logging
import math
import time
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
# ellenőrizhető — a többi az I2C-buszon dől el. A vágás itt SZÖGBEN történik, nem
# pulzusban, és ez nem stílus kérdése: ha csak a pulzust vágnánk, a nyilvántartott szög
# elszállna a fizikai határon túlra (három „balra 45" után 135 fokot hinne), és a
# következő „jobbra 10" NEM mozdítaná meg a kamerát, mert még mindig a határon kívül
# volna. A robot ilyenkor néma és mozdulatlan — a legrosszabb hibafajta a színpadon.

def szog_hatarok(cfg: CameraSettings) -> tuple[float, float]:
    """A biztonsági pulzus-sávnak megfelelő szögtartomány, a középhez képest."""
    return ((cfg.min_ms - cfg.centre_ms) / cfg.ms_per_deg,
            (cfg.max_ms - cfg.centre_ms) / cfg.ms_per_deg)


def vagott_szog(cfg: CameraSettings, szog: float) -> float:
    also, felso = szog_hatarok(cfg)
    return min(max(szog, also), felso)


def lepesekre(fok: float, lepes: float) -> list[float]:
    """Egy elmozdulást egyenlő-ish lépésekre bont, az ÖSSZEG pontos megtartásával.

    A szervónak nincs sebesség-bemenete: egy nagy lépésre teljes gyorsasággal odaugrik.
    A lassú, folyamatos pásztázás CSAK így áll elő. Az összeg pontossága nem
    kozmetika — a gesztus végén a kamerának oda kell visszaállnia, ahonnan indult, és
    egy lebegőpontos maradék minden pásztázásnál elcsúsztatná.
    """
    if fok <= 0:
        return []
    darab = max(1, math.ceil(fok / lepes))
    return [fok / darab] * darab


def pulzus_ms(cfg: CameraSettings, szog: float) -> float:
    """Szög (a középhez képest) -> pulzushossz. A vágás a hívó dolga."""
    return cfg.centre_ms + szog * cfg.ms_per_deg


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
        self._keret_ms = 1000.0 / self._cfg.pwm_frequency_hz
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._pca = PCA9685(self._i2c, address=G.PCA9685_ADDR)
        self._pca.frequency = self._cfg.pwm_frequency_hz
        self._pan_szog = 0.0
        self._tilt_szog = 0.0
        self._kiad(G.PAN_CHANNEL, 0.0)
        self._kiad(G.TILT_CHANNEL, 0.0)

    # --- alacsony szint ---

    def _kiad(self, csatorna: int, szog: float) -> None:
        ms = pulzus_ms(self._cfg, szog)
        # A 12 bites regisztert a könyvtár 16 bites `duty_cycle`-ből számolja (16-tal
        # oszt), ezért megy ide a 0xFFFF és nem a 0x0FFF.
        self._pca.channels[csatorna].duty_cycle = int(ms / self._keret_ms * 0xFFFF)

    def _mozgat(self, csatorna: int, jelenlegi: float, delta: float, tengely: str) -> float:
        cel = jelenlegi + delta
        vagott = vagott_szog(self._cfg, cel)
        if vagott != cel:
            # NEM kivétel: a "nézz még balrább" a demón álljon meg szépen a végállásnál.
            # De nem is néma: e nélkül a "nem fordult tovább" megkülönböztethetetlen
            # volna egy döglött szervótól.
            log.warning("%s: %.1f fok a határon kívül, vágva %.1f fokra "
                        "(sáv: %.1f..%.1f ms)", tengely, cel, vagott,
                        self._cfg.min_ms, self._cfg.max_ms)
        self._kiad(csatorna, vagott)
        return vagott

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
        self._pan_szog = self._mozgat(G.PAN_CHANNEL, self._pan_szog,
                                      elojel * degrees, "pan")

    def tilt(self, direction: str, degrees: float) -> None:
        elojel = self._elojel(direction,
                              {"up": G.TILT_UP_SIGN, "down": -G.TILT_UP_SIGN}, "tilt")
        self._tilt_szog = self._mozgat(G.TILT_CHANNEL, self._tilt_szog,
                                       elojel * degrees, "tilt")

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
        kezdo = (self._pan_szog, self._tilt_szog)
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
            # lépés a határba ütközött, az oda-vissza már nem egyenlíti ki magát, és a
            # kamera elcsúszva maradna. Ezért kifejezett visszaállás.
            self._pan_szog, self._tilt_szog = kezdo
            self._kiad(G.PAN_CHANNEL, kezdo[0])
            self._kiad(G.TILT_CHANNEL, kezdo[1])

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
