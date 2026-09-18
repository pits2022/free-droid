"""Alvó póz: leálláskor a fej előre-le billen, és TARTVA marad.

Két haszna van, és mindkettő fizikai: bekapcsoláskor a `home()` középre hajtás
LÁTVÁNYOS (a fej felemelkedik — „felébred"), szállításkor pedig az előre billentett
kamera nem akad be.

A szervók a póz után is kapnak jelet — ld. `test_camera_close.py`: elengedve a tilt a
gimbal súlyától hanyatt esik. Az alvó póz tehát NEM elengedés, hanem egy másik tartott
helyzet.
"""

from __future__ import annotations

import types

import pytest

from freedroid.camera import szog_hatarok, tengelyek
from freedroid.config.settings import CameraSettings, load_settings
from freedroid.orchestrator import Orchestrator

from test_orchestrator_execute import FakeCamera, FakeMotion, FakeWatchdog


def _naplozo_kamera_es_motor(naplo: list[str]):
    class Kamera(FakeCamera):
        def sleep(self) -> None:
            naplo.append("kamera.sleep")

        def close(self) -> None:
            naplo.append("kamera.close")

    class Motor(FakeMotion):
        def close(self) -> None:
            naplo.append("motor.close")
            super().close()

    return Kamera(), Motor()


def test_close_stops_the_motors_before_the_camera_pose():
    """🔴 BIZTONSÁGI SORREND (PR #146 review).

    A póz holtjáték-kompenzált, tehát tengelyenként `step_s` (0,35 s) várakozás — egy
    beragadt I2C-busz ennél sokkal tovább is tarthat. Ha a motor lezárása (ami `stop()`-pal
    kezdődik) ezután jönne, a lánctalpak addig FUTHATNÁNAK, immár watchdog nélkül.
    A póz kényelem, a megállás nem.

    És a pózolás mégis a KAMERA lezárása előtt van: utána már nincs mivel mozgatni.
    """
    naplo: list[str] = []
    k, m = _naplozo_kamera_es_motor(naplo)
    Orchestrator(motion=m, camera=k, watchdog=FakeWatchdog()).close()
    assert naplo == ["motor.close", "kamera.sleep", "kamera.close"]


def test_a_failing_ring_close_does_not_strand_the_motors():
    """PR #146 review: a `led.close()` őrizetlen volt. Egy hibája elvitte volna a
    watchdogot, a motort ÉS a kamerát — járó lánctalpak egy kilépő folyamat után."""
    naplo: list[str] = []
    k, m = _naplozo_kamera_es_motor(naplo)
    o = Orchestrator(motion=m, camera=k, watchdog=FakeWatchdog())

    class RosszGyuru:
        def close(self):
            raise OSError("SPI hiba")

    o.led = RosszGyuru()
    o.close()
    assert m.closed, "a gyűrű hibája elvitte a motor lezárását"
    assert naplo == ["motor.close", "kamera.sleep", "kamera.close"]


def test_close_survives_a_camera_that_cannot_pose():
    """Egy `sleep()` nélküli kamera (régi dublőr, más vezérlő) ne buktassa a lezárást —
    és ami fontosabb, a MOTOR lezárása se maradjon el miatta."""
    k = FakeCamera()                      # nincs `sleep()` metódusa
    m = FakeMotion()
    o = Orchestrator(motion=m, camera=k, watchdog=FakeWatchdog())
    o.close()                             # nem dobhat
    assert m.closed, "a kamera hiánya elvitte a motor lezárását"


def test_a_failing_pose_still_closes_the_camera():
    """Egy I2C-hiba a pózolásban ne hagyja nyitva a buszt — a póz kényelem, a
    lezárás kötelesség."""
    naplo: list[str] = []

    class Rossz(FakeCamera):
        def sleep(self):
            naplo.append("sleep")
            raise OSError("I2C hiba")

        def close(self):
            naplo.append("close")

    o = Orchestrator(motion=FakeMotion(), camera=Rossz(), watchdog=FakeWatchdog())
    o.close()
    assert naplo == ["sleep", "close"]


# --- a póz maga -------------------------------------------------------------------


def _kamera_dublorrel(cfg: CameraSettings, valodi_iras: bool = False):
    """`PanTiltCamera` valódi geometriával, de I2C nélkül."""
    from freedroid.camera import PanTiltCamera

    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = {"pan", "tilt"}
    k.beallitasok = []
    if valodi_iras:
        # A VALÓDI `_beall_holtjatek_nelkul` fut, csak a busz hamis: így a teszt azt méri,
        # mit ír a kód a csatornákra, nem azt, hogy meghívott-e egy lambdát.
        k._keret_ms = 1000.0 / cfg.pwm_frequency_hz
        k._pca = types.SimpleNamespace(
            channels=[types.SimpleNamespace(duty_cycle=SENTINEL) for _ in range(16)])
    else:
        k._beall_holtjatek_nelkul = lambda t, szog: (
            k.beallitasok.append((t.nev, szog)), k._szog.__setitem__(t.nev, szog))
    return k


def test_sleep_tilts_the_head_forward_and_down():
    k = _kamera_dublorrel(load_settings().camera)
    k.sleep()
    assert dict(k.beallitasok)["tilt"] < 0, "az alvó póz nem billentette előre a fejet"


def test_sleep_is_a_no_op_when_disabled():
    """Kikapcsolva a leállás NE nyúljon a szervókhoz — egy felpolcolt, bekötött
    roboton a Teremtő ezt kérheti."""
    k = _kamera_dublorrel(CameraSettings(sleep_pose_enabled=False))
    k.sleep()
    assert k.beallitasok == []


def test_the_default_sleep_pose_is_physically_reachable():
    """🔴 EZ A VALÓDI ŐR. A tilt tartománya a MÉRT skálával +-53,6 fok, nem a
    `min_ms`/`max_ms` kommentjében álló +-80 (az a javítás előtti 0,0112-es skálából
    maradt ott). Egy -60 fokos alvó póz tehát NÉMÁN a határra vágódna, és a fej nem
    oda állna, ahova a config mondja.
    """
    cfg = load_settings().camera
    pan_t, tilt_t = tengelyek(cfg)
    for t, szog in ((pan_t, cfg.sleep_pan_deg), (tilt_t, cfg.sleep_tilt_deg)):
        also, felso = szog_hatarok(t)
        assert also <= szog <= felso, (
            f"az alvó póz {t.nev} szöge ({szog}) a {also:.1f}..{felso:.1f} fokos "
            f"tartományon kívül van — a szervó a határon állna meg")


@pytest.mark.parametrize("mezo,ertek", [("sleep_tilt_deg", -160.0),
                                        ("sleep_pan_deg", 200.0)])
def test_an_unreachable_sleep_pose_is_rejected_at_startup(mezo, ertek):
    """Indulásnál hasaljon el, ne a színpadon egy félrenéző fejjel."""
    with pytest.raises(ValueError, match="alvó póz"):
        CameraSettings(**{mezo: ertek})


SENTINEL = 12345        # se nem 0 (elengedve), se nem érvényes pulzus


def test_sleep_holds_the_servos_it_does_not_release_them():
    """A póz tartott helyzet, nem elengedés — ld. `test_camera_close.py`.

    ⚠️ EZ A TESZT A VALÓDI ÍRÁSI ÚTON MEGY (`_beall_holtjatek_nelkul` NINCS kicserélve).
    Az első változata dublőrrel ment és 0-ról indította a csatornákat, majd 0-t várt —
    vagyis akkor is átment volna, ha a `sleep()` full-off-fal ELENGEDI a szervókat
    (PR #146 review). A sentinel kezdőérték és a nem-nulla elvárás ezt zárja ki.
    """
    k = _kamera_dublorrel(load_settings().camera, valodi_iras=True)
    k.sleep()
    tilt = k._pca.channels[k._tilt_t.csatorna].duty_cycle
    assert tilt != SENTINEL, "a sleep() nem állította be a tiltet"
    assert tilt > 0, "a sleep() ELENGEDTE a tiltet (duty_cycle 0) — a fej hanyatt esne"
