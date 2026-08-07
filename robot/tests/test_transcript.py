"""Az átirat-napló szerződése: minden szakasz külön mérhető, és SOHA nem áll meg tőle a robot."""

import json

import pytest

from freedroid.orchestrator.transcript import Interakcio, log, olvas


def test_log_minden_szakaszt_kulon_ment(tmp_path):
    """A nyers átirat, a betalált chunkok és a modell külön mezőben — enélkül a napló
    nem tudja megválaszolni, hogy a Whisper értette félre vagy a keresés hibázott."""
    p = tmp_path / "transcript.jsonl"
    log(Interakcio(hallott="mi az a jó tengrit",
                   valasz="Nincs rá megbízható adatom.",
                   forras="edge", modell="szabi-3b-v11e3",
                   rag_chunkok=[], rag_cimek=[], prompt="mi az a jó tengrit",
                   toolok=[], stt_ms=820, llm_ms=3100), p)
    log(Interakcio(hallott="menj előre két métert", valasz="Megyek, Teremtőm.",
                   forras="cloud", modell="szabi-8b-v11",
                   toolok=["move forward 2"]), p)

    sorok = olvas(p)
    assert len(sorok) == 2
    elso = sorok[0]
    assert elso["hallott"] == "mi az a jó tengrit"     # a NYERS átirat, érintetlenül
    assert elso["rag_chunkok"] == []                    # üres találat -> ez a diagnózis
    assert elso["forras"] == "edge" and elso["modell"] == "szabi-3b-v11e3"
    assert sorok[1]["toolok"] == ["move forward 2"]
    assert all("ts" in s for s in sorok)


def test_a_naplo_hibaja_nem_allitja_meg_a_robotot(tmp_path, capsys):
    """Tele lemez vagy írhatatlan útvonal nem némíthatja el Szabit a színpadon."""
    utvonal = tmp_path / "fajl.txt"
    utvonal.write_text("nem könyvtár", encoding="utf-8")
    log(Interakcio(hallott="teszt"), utvonal / "alatta" / "transcript.jsonl")
    assert "transcript" in capsys.readouterr().err   # jelezzük, de nem dobunk


def test_serult_sor_atugorva(tmp_path):
    p = tmp_path / "transcript.jsonl"
    log(Interakcio(hallott="ép sor"), p)
    with p.open("a", encoding="utf-8") as f:
        f.write("{ez nem json\n")
    log(Interakcio(hallott="másik ép sor"), p)
    assert [s["hallott"] for s in olvas(p)] == ["ép sor", "másik ép sor"]


def test_hianyzo_naplo_ures_lista(tmp_path):
    assert olvas(tmp_path / "nincs.jsonl") == []


@pytest.mark.parametrize("mezo", ["hallott", "valasz", "forras", "modell",
                                  "rag_chunkok", "prompt", "toolok"])
def test_a_lanc_minden_szakasza_szerepel(tmp_path, mezo):
    """A Teremtő kérése: legyen látható, mit hallott a Whisper, mi ment a RAG-ra,
    és mit válaszolt MELYIK modell. Ha egy mező eltűnik, ez a teszt fog szólni."""
    p = tmp_path / "t.jsonl"
    log(Interakcio(hallott="x"), p)
    assert mezo in json.loads(p.read_text(encoding="utf-8").splitlines()[0])
