"""KattintoTrigger: fehérlista + csak lenyomás + hiányzó eszköz nem végzetes."""
from __future__ import annotations

import queue
import struct

from freedroid.voice import trigger
from freedroid.voice.trigger import Esemeny, KattintoTrigger

REKORD = struct.Struct("llHHi")


def _esemeny(kod: int, ertek: int, tipus: int = 1) -> bytes:
    return REKORD.pack(0, 0, tipus, kod, ertek)


def test_lenyomas_leképezve_ismeretlen_es_felengedes_eldobva(tmp_path, monkeypatch):
    monkeypatch.setattr(trigger.fcntl, "ioctl", lambda *a: 0)   # sima fájlon nincs EVIOCGRAB
    eszkoz = tmp_path / "x-event-kbd"
    eszkoz.write_bytes(
        _esemeny(109, 1)            # PageDown lenyomás -> FIGYELJ
        + _esemeny(109, 0)          # felengedés -> semmi
        + _esemeny(109, 2)          # ismétlés -> semmi
        + _esemeny(30, 1)           # KEY_A: nincs a fehérlistán -> semmi
        + _esemeny(4, 1, tipus=4)   # EV_MSC scancode -> semmi
        + _esemeny(104, 1)          # PageUp lenyomás -> ALLJ
    )
    sor: queue.Queue[Esemeny] = queue.Queue()
    forras = KattintoTrigger(minta=str(tmp_path / "*-event-kbd"))
    forras.start(sor)
    assert forras._szal is not None
    forras._szal.join(timeout=2)
    assert [sor.get(timeout=1), sor.get(timeout=1)] == [Esemeny.FIGYELJ, Esemeny.ALLJ]
    assert sor.empty()
    forras.close()


def test_hianyzo_eszkoz_nem_vegzetes(tmp_path):
    sor: queue.Queue[Esemeny] = queue.Queue()
    forras = KattintoTrigger(minta=str(tmp_path / "nincs-*"))
    forras.start(sor)            # nem dob
    assert forras._szal is None
    forras.close()
