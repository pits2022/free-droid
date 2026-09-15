"""A `close()` NEM engedi el a szervókat — szándékosan (mérve 2026-09-15).

Elengedve (full-off) a tilt a gimbal súlyától hanyatt esett. Ez a teszt a döntést
rögzíti: egy jövőbeli „a close() engedje el a szervókat" javítás itt bukjon, ne a
színpadon egy hanyatt fekvő kamerával.
"""

from __future__ import annotations

import types

from freedroid.camera import PanTiltCamera


def test_close_does_not_release_servo_channels():
    k = object.__new__(PanTiltCamera)
    writes: list[tuple[int, object]] = []

    class Channel:
        def __init__(self, i: int) -> None:
            self.i = i

        def __setattr__(self, name, value):
            if name == "duty_cycle":
                writes.append((self.i, value))
            object.__setattr__(self, name, value)

    calls: list[str] = []
    k._pca = types.SimpleNamespace(channels=[Channel(i) for i in range(16)],
                                   deinit=lambda: calls.append("pca"))
    k._i2c = types.SimpleNamespace(deinit=lambda: calls.append("i2c"))
    k.close()
    assert writes == [], "a close() hozzányúlt a szervócsatornákhoz — a tilt hanyatt esne"
    assert calls == ["pca", "i2c"]
