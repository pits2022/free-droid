"""A szervók ELENGEDÉSE: beállás után a PCA9685 csatornák full-off-ba mennek.

🔴 MÉRVE 2026-09-15, a Pi-n: álló kamera mellett a szervók folyamatosan rángtak, és
időnként parancs nélkül is mozdultak — a `freedroid` LEÁLLÍTÁSA UTÁN is. A regiszterek
szerint a PCA9685 kilépés után is hajtotta őket (ch0 1,65 ms, ch1 1,50 ms): a
`PCA9685.deinit()` csak a MODE1-et állítja vissza, a csatornákat nem. Kézzel full-off-ra
állítva a rángás AZONNAL megszűnt, és a tilt a saját súrlódásán a helyén maradt — tehát
a tartott jel mellett a szervó a hullámzó tápon a pozíció körül „vadászott".

A példány `object.__new__`-val készül (a konstruktor Pi-only), mint a
`test_camera_home.py`-ban; a `_pca` egy hamis csatornalista.
"""

from __future__ import annotations

import threading
import types

from freedroid.camera import PanTiltCamera, tengelyek
from freedroid.config import gpio as G
from freedroid.config.settings import load_settings


class HamisPCA:
    def __init__(self) -> None:
        self.channels = [types.SimpleNamespace(duty_cycle=None) for _ in range(16)]
        self.deinit_hivva = False

    def deinit(self) -> None:
        self.deinit_hivva = True


def kamera() -> tuple[PanTiltCamera, HamisPCA]:
    cfg = load_settings().camera
    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._keret_ms = 1000.0 / cfg.pwm_frequency_hz
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = set()
    k._pca = HamisPCA()
    k._i2c = types.SimpleNamespace(deinit=lambda: None)
    k._zar = threading.Lock()
    k._elengedo = None
    return k, k._pca


def szervo_csatornak(pca: HamisPCA) -> tuple[object, object]:
    return pca.channels[G.PAN_CHANNEL].duty_cycle, pca.channels[G.TILT_CHANNEL].duty_cycle


def test_minden_kiadas_UTEMEZ_egy_elengedest():
    k, pca = kamera()
    k.pan("left", 10)
    assert k._elengedo is not None and k._elengedo.is_alive()
    assert szervo_csatornak(pca)[0], "a pan nem adott ki pulzust"
    k._elengedo.cancel()


def test_az_uj_kiadas_ATUTEMEZI_a_korabbi_elengedest():
    """Gesztus közben (bólintás 0,35 s, pásztázás 0,04 s lépésköz) nem engedhet el."""
    k, _ = kamera()
    k.pan("left", 10)
    elso = k._elengedo
    k.tilt("up", 5)
    assert elso.finished.is_set(), "a korábbi elengedés nem lett törölve"
    assert k._elengedo is not elso
    k._elengedo.cancel()


def test_az_elengedes_MINDKET_szervocsatornat_full_offra_allitja():
    """Az adafruit `duty_cycle = 0` a full-off bitet írja (0x1000), nem egy 0 ms-os pulzust."""
    k, pca = kamera()
    k.pan("left", 10)
    k._elengedo.cancel()
    k._elenged()
    assert szervo_csatornak(pca) == (0, 0)


def test_a_close_ELENGEDI_a_szervokat_a_deinit_ELOTT():
    """Mért hiba: a `deinit()` önmagában tartva hagyta a jelet kilépés után is."""
    k, pca = kamera()
    k.tilt("down", 5)
    k.close()
    assert szervo_csatornak(pca) == (0, 0)
    assert pca.deinit_hivva
    assert k._elengedo.finished.is_set(), "a close() után függő elengedés maradt"
