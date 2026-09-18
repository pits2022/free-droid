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


class AlvoKamera(FakeCamera):
    """A `FakeCamera` + a leállás sorrendjének rögzítése."""

    def __init__(self) -> None:
        super().__init__()
        self.sorrend: list[str] = []

    def sleep(self) -> None:
        self.sorrend.append("sleep")

    def close(self) -> None:
        self.sorrend.append("close")


def test_close_poses_the_camera_before_releasing_the_bus():
    """A sorrend a lényeg: lezárt I2C után már nem lehet pózolni."""
    k = AlvoKamera()
    o = Orchestrator(motion=FakeMotion(), camera=k, watchdog=FakeWatchdog())
    o.close()
    assert k.sorrend == ["sleep", "close"]


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


def _kamera_dublorrel(cfg: CameraSettings):
    """`PanTiltCamera` valódi geometriával, de I2C nélkül."""
    from freedroid.camera import PanTiltCamera

    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = {"pan", "tilt"}
    k.beallitasok = []
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


def test_sleep_does_not_release_the_servo_channels():
    """A póz tartott helyzet, nem elengedés — ld. `test_camera_close.py`."""
    from freedroid.camera import PanTiltCamera

    k = _kamera_dublorrel(load_settings().camera)
    k._pca = types.SimpleNamespace(
        channels=[types.SimpleNamespace(duty_cycle=0) for _ in range(16)])
    k.sleep()
    assert all(getattr(cs, "duty_cycle") == 0 for cs in k._pca.channels), \
        "a sleep() közvetlenül a csatornákhoz nyúlt — a tilt hanyatt eshet"
    assert PanTiltCamera.sleep is not None
