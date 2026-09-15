"""`PanTiltCamera.move_to()` — abszolút póz a holtjáték-kompenzált úton.

A konstruktor Pi-only (I2C, PCA9685), ezért a példány `object.__new__`-val készül és csak
a kiadó ág (`_kiad`) van kicserélve — mint a `test_camera_home.py`-ban. A vizsgált logika
a VALÓDI kód.
"""

from __future__ import annotations

import pytest

from freedroid.camera import PanTiltCamera, tengelyek
from freedroid.config import gpio as G
from freedroid.config.settings import Settings, VisionSettings, load_settings


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("freedroid.camera.time.sleep", lambda s: None)


def camera() -> tuple[PanTiltCamera, list[tuple[str, float]]]:
    cfg = load_settings().camera
    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = {"pan", "tilt"}
    outputs: list[tuple[str, float]] = []
    k._kiad = lambda t, szog: outputs.append((t.nev, szog))  # type: ignore[method-assign]
    return k, outputs


def test_move_to_reaches_the_absolute_target_with_sign():
    k, outputs = camera()
    assert k.move_to(45.0, -30.0) is True
    assert k._szog == {"pan": G.PAN_LEFT_SIGN * 45.0, "tilt": G.TILT_UP_SIGN * -30.0}
    # az UTOLSÓ kiadás tengelyenként maga a cél (előtte jöhet a holtjáték-alálövés)
    last = {name: angle for name, angle in outputs}
    assert last == {"pan": G.PAN_LEFT_SIGN * 45.0, "tilt": G.TILT_UP_SIGN * -30.0}


def test_move_to_is_absolute_not_relative():
    k, _ = camera()
    k.move_to(45.0, 0.0)
    k.move_to(-45.0, 0.0)
    assert k._szog["pan"] == G.PAN_LEFT_SIGN * -45.0


def test_move_to_current_pose_does_not_move():
    """A kör eleji `home()` után az `Előre (0, 0)` NEM mozdít — és nem kell rá `settle_s`."""
    k, outputs = camera()
    assert k.move_to(0.0, 0.0) is False
    assert outputs == []


def test_move_to_zero_is_a_real_target():
    """`bool(0.0)` hamis — a 0 fok mégis érvényes cél, ha máshol áll a fej."""
    k, outputs = camera()
    k.move_to(45.0, 0.0)
    outputs.clear()
    assert k.move_to(0.0, 0.0) is True
    assert ("pan", 0.0) in outputs


def test_move_to_clips_out_of_range_target(caplog):
    k, _ = camera()
    k.move_to(999.0, 0.0)
    assert abs(k._szog["pan"]) < 999.0
    assert "határon kívül" in caplog.text


@pytest.mark.parametrize("field", ["look_side_deg", "look_up_deg", "look_down_deg", "settle_s"])
def test_non_positive_look_settings_fail_at_startup(field):
    with pytest.raises(ValueError, match=f"vision.{field}"):
        VisionSettings(**{field: 0.0})


@pytest.mark.parametrize("field, value", [("look_side_deg", 90.1), ("look_up_deg", 180.0),
                                          ("look_down_deg", 91.0), ("settle_s", 3.1)])
def test_too_large_look_settings_fail_at_startup(field, value):
    """Egy elgépelt env (`FREEDROID_VISION_SETTLE_S=100`) ne némítsa el a kört, és egy
    `LOOK_SIDE_DEG=180` ne vigye a fejet végállásba (PR #135 review 2)."""
    with pytest.raises(ValueError, match=f"vision.{field}"):
        VisionSettings(**{field: value})


def test_look_settings_defaults():
    v = Settings().vision
    assert (v.look_side_deg, v.look_up_deg, v.look_down_deg, v.settle_s) == (45.0, 30.0, 30.0, 0.5)
