"""A tool-megbízhatóság pontozása ne mozduljon el a hátunk mögött.

A `tool_reliability.py` egy MÉRŐESZKÖZ: ha az `ertekel()` viselkedése változik, a
korábbi körök számai összehasonlíthatatlanná válnak — csendben, mert a riport
ugyanúgy lefut. Ezért a 2026-08-05-i kör NYERS válaszait újrapontozzuk, és a
commitolt pontszámokhoz mérjük. Ha ez elhasal, az vagy hiba, vagy szándékos
mérce-változtatás — utóbbihoz a régi köröket újra kell futtatni, nem a tesztet
igazítani.
"""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TRAINING = _ROOT / "training"
_RAW = _TRAINING / "tool_reliability_raw_2026-08-05.json"

sys.path.insert(0, str(_TRAINING))
from tool_reliability import _ossze, ertekel


@pytest.mark.parametrize("a, b, vart", [
    (2.0, 2, True),        # move distance float, JSON-ben int
    (90, "90", True),      # turn degrees int, JSON-ben string
    ("slow", "slow", True),
    ("left", "right", False),
    (None, "left", False),  # a modell meg sem adta az argot
])
def test_ossze_a_szamalakot_nem_szamitja(a, b, vart):
    assert _ossze(a, b) is vart


def test_a_2026_08_05_i_kor_ujrapontozva_ugyanazt_adja():
    raw = json.loads(_RAW.read_text(encoding="utf-8"))
    kerdesek = {k["id"]: k for k in
                json.loads((_TRAINING / "tool_reliability.json").read_text(
                    encoding="utf-8"))["kerdesek"]}
    elteres = {}
    for modell, qs in raw["eredmenyek"].items():
        for qid, d in qs.items():
            uj = sum(ertekel(kerdesek[qid], v)[0] for v in d["valaszok"])
            if uj != d["pont"]:
                elteres[f"{modell}/{qid}"] = (d["pont"], uj)
    assert not elteres, f"a pontozás elmozdult: {elteres}"
