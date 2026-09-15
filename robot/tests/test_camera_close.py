"""A `close()` NEM engedi el a szervókat — szándékosan (mérve 2026-09-15).

Elengedve (full-off) a tilt a gimbal súlyától hanyatt esett. Ez a teszt a döntést
rögzíti: egy jövőbeli „a close() engedje el a szervókat" javítás itt bukjon, ne a
színpadon egy hanyatt fekvő kamerával.
"""

from __future__ import annotations

import types

from freedroid.camera import PanTiltCamera


def test_a_close_NEM_irja_full_offra_a_szervocsatornakat():
    k = object.__new__(PanTiltCamera)
    irasok: list[tuple[int, object]] = []

    class Csatorna:
        def __init__(self, i: int) -> None:
            self.i = i

        def __setattr__(self, nev, ertek):
            if nev == "duty_cycle":
                irasok.append((self.i, ertek))
            object.__setattr__(self, nev, ertek)

    hivasok: list[str] = []
    k._pca = types.SimpleNamespace(channels=[Csatorna(i) for i in range(16)],
                                   deinit=lambda: hivasok.append("pca"))
    k._i2c = types.SimpleNamespace(deinit=lambda: hivasok.append("i2c"))
    k.close()
    assert irasok == [], "a close() hozzányúlt a szervócsatornákhoz — a tilt hanyatt esne"
    assert hivasok == ["pca", "i2c"]
