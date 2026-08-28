"""Az átirat-napló szerződése: minden szakasz külön mérhető, és SOHA nem áll meg tőle a robot."""

import json

import pytest

from freedroid.orchestrator.transcript import Interakcio, log, olvas


@pytest.fixture(autouse=True)
def debug_poszturaban(monkeypatch):
    """A tesztek BELEEGYEZNEK a rögzítésbe, mert az alapértelmezés a NEM-rögzítés.

    Ez a polaritás a Teremtő 2026-08-10-i döntése: egy kapcsoló, amit ki KELL kapcsolni,
    előbb-utóbb bekapcsolva marad, és a hibája a Teremtő beszélgetése egy lopható
    kártyán. Hogy a kapu tényleg zárva van alapból, azt a fájl VÉGÉN külön teszt méri —
    ez a fixture épp azt fedné el."""
    monkeypatch.setenv("FREEDROID_DEBUG", "1")


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
                                  "rag_chunkok", "rag_cimek", "prompt", "toolok",
                                  "stt_ms", "llm_ms", "hiba"])
def test_a_lanc_minden_szakasza_szerepel(tmp_path, mezo):
    """A Teremtő kérése: legyen látható, mit hallott a Whisper, mi ment a RAG-ra,
    és mit válaszolt MELYIK modell. Ha egy mező eltűnik, ez a teszt fog szólni."""
    p = tmp_path / "t.jsonl"
    log(Interakcio(hallott="x"), p)
    assert mezo in json.loads(p.read_text(encoding="utf-8").splitlines()[0])


# A "SOSEM dob" szerződés két útja, amit az első változat NEM tartott be: az
# `except OSError` mellett a `TypeError` és a `UnicodeEncodeError` (ez `ValueError`,
# nem `OSError`) kiszökött. Mindkettő valós, nem elméleti — lásd a `log()` docstringjét.
def test_nem_szerializalhato_mezo_nem_dob(tmp_path, capsys):
    """Elég egy `Path` a `toolok`-ban, és az első változat TypeError-t dobott."""
    p = tmp_path / "t.jsonl"
    log(Interakcio(hallott="x", toolok=[tmp_path]), p)      # nem dobhat
    assert capsys.readouterr().err == ""                     # sőt: le is MENTETTE
    assert str(tmp_path) in olvas(p)[0]["toolok"][0]


def test_surrogate_a_whisper_atiratban_nem_dob(tmp_path):
    """A `hallott` a Whisper NYERS átirata: egy `surrogateescape`-pel dekódolt hibás
    bájtsor lone surrogate-ot hoz ide, és az `UnicodeEncodeError`-t dobott a write-ban.
    A sor maradjon meg — rontott karakterrel is —, mert a napló a diagnosztikáért van."""
    p = tmp_path / "t.jsonl"
    log(Interakcio(hallott="rossz \udcff bájt", modell="szabi-8b-v11"), p)
    sorok = olvas(p)
    assert len(sorok) == 1
    assert sorok[0]["modell"] == "szabi-8b-v11"              # a többi mező sértetlen


# ── a kapu maga ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ertek", ["", "0", "false", "nem", "off", "hamis"])
def test_debug_NELKUL_semmi_nem_rogzul(tmp_path, monkeypatch, ertek):
    """A demó-posztúra tulajdonsága, tesztként kimondva: *egy ellopott SD-kártya ne
    adjon semmit, ami nincs a publikus repóban*. A napló az EGYETLEN dolog a Pi-n, ami
    ezen elbukhat — egy WireGuard-kulcsot lehet forgatni, egy elhangzott mondatot nem.

    A `"hamis"` eset nem vicc: `bool("hamis")` Pythonban IGAZ, tehát egy naiv
    igazságérték-vizsgálat pont a magyarul kikapcsolt naplót hagyná bekapcsolva."""
    monkeypatch.setenv("FREEDROID_DEBUG", ertek)
    p = tmp_path / "transcript.jsonl"

    log(Interakcio(hallott="valami, ami SOHA nem kerülhet lemezre"), p)

    assert not p.exists(), f"FREEDROID_DEBUG={ertek!r} mellett is írt a napló"


def test_a_kapu_a_FUGGVENYBEN_van_nem_a_hivoknal(tmp_path, monkeypatch):
    """Egy hívónál kihagyott kapu csendben visszahozná az egész kockázatot, ezért a
    kapu a `log()`-ban van — ez a teszt azt rögzíti, hogy ott is maradjon."""
    monkeypatch.delenv("FREEDROID_DEBUG", raising=False)
    p = tmp_path / "transcript.jsonl"

    log(Interakcio(hallott="x"), p)
    assert not p.exists()

    monkeypatch.setenv("FREEDROID_DEBUG", "igen")
    log(Interakcio(hallott="x"), p)
    assert len(olvas(p)) == 1, "debug posztúrában viszont írnia KELL"
