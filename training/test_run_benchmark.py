#!/usr/bin/env python3
"""A run_benchmark.py timeout-rezilienciájának és a vak/bináris pontozásnak az
ellenőrzése (hálózat nélkül).

Futtatás: `python test_run_benchmark.py` vagy `pytest test_run_benchmark.py`.
A fedett elágazások: (1) egy kérdés time-outja NEM állíthatja le a futást
(különben a már kész, drága oszlopok eredménye elveszne), a setup-hiba viszont
igen; (2) a vak markdown -> kézi pontozás -> --decode kör visszaadja az eredeti
modell-hozzárendelést, és a vak kimenet nem szivárogtat oszlop-azonosítót.
"""

import json
import random
from pathlib import Path

import run_benchmark as rb

_KERDESEK = [{"id": f"q{i}", "dimenzio": "koherencia", "kerdes": "?"} for i in range(3)]
_TARGET = rb.Target(label="teszt", model="m", rag=False)


def _raise(exc):
    # **kw: a hívó a temperature-t (és bármi későbbi opciót) kulcsszóval adja át — a
    # stubnak nem szabad a szignatúra bővítésén elhasadnia, mert a teszt tárgya a
    # timeout-viselkedés, nem a paraméterlista.
    def _f(model, prompt, timeout, **kw):
        raise exc
    return _f


def test_timeout_degrades_and_run_continues() -> None:
    orig = rb.ollama_generate
    rb.ollama_generate = _raise(rb.GenerationTimeout("'m' > 600s"))
    try:
        res = rb.run_target(_TARGET, _KERDESEK, rag_ctx=None, rag_dims=None, timeout=600.0)
    finally:
        rb.ollama_generate = orig
    assert len(res) == 3, "mind a 3 kérdés meglegyen — a futás nem állhatott le"
    assert all(v["valasz"].startswith("⏱ KIHAGYVA") for v in res.values())
    assert all(v["tok_s"] is None for v in res.values())
    assert all(v["skipped"] is True for v in res.values()), \
        "a degradált cella strukturált skipped=True jelet kap (a judge ezt látva kihagyja)"


def test_connection_error_degrades_to_generation_timeout() -> None:
    # Ha az Ollama menet közben elhal (ConnectionResetError), az NEM hard fail:
    # GenerationTimeout-tá alakul, hogy a cella a timeouttal azonos módon degradáljon.
    import urllib.request
    orig = urllib.request.urlopen

    def _boom(*_a, **_k):
        raise ConnectionResetError("ollama meghalt")

    urllib.request.urlopen = _boom
    try:
        rb.ollama_generate("m", "?", timeout=1.0)
    except rb.GenerationTimeout:
        pass  # elvárt
    else:
        raise AssertionError("ConnectionError-nak GenerationTimeout-tá kell alakulnia")
    finally:
        urllib.request.urlopen = orig


def test_setup_error_still_hard_fails() -> None:
    orig = rb.ollama_generate
    rb.ollama_generate = _raise(rb.BenchmarkError("404 nincs modell"))
    try:
        rb.run_target(_TARGET, _KERDESEK, None, None, 600.0)
    except rb.BenchmarkError:
        return  # elvárt: a setup-hiba felszáll (hard fail)
    finally:
        rb.ollama_generate = orig
    raise AssertionError("a BenchmarkError-nak hard fail-nek kell maradnia")


# --------------------------------------------------------------------------- #
# Vak pontozás + horgony + dekódolás
# --------------------------------------------------------------------------- #
_QK = [{"id": "id_01", "dimenzio": "identitas", "kerdes": "Ki vagy?"},
       {"id": "ko_01", "dimenzio": "koherencia", "kerdes": "Mesélj."}]
_TARGETS = [rb.Target(label="szabi-8b", model="szabi-8b", rag=False),
            rb.Target(label="szabi-3b", model="szabi-3b", rag=False)]


def _cella(valasz, tok_s=99.9):
    return {"valasz": valasz, "tok_s": tok_s, "forras": ["Yotengrit"], "skipped": False}


def _results():
    return {"szabi-8b": {q["id"]: _cella(f"nyolc-{q['id']}", 4.2) for q in _QK},
            "szabi-3b": {q["id"]: _cella(f"harom-{q['id']}", 250.0) for q in _QK}}


def test_blind_markdown_hides_model_identity() -> None:
    plan = rb.build_blind_plan(_QK, ["szabi-8b", "szabi-3b"], set(), None, random.Random(1))
    md = rb.render_markdown(_TARGETS, _QK, _results(), rag=True, plan=plan,
                            key_name="kulcs.json")
    # A kérdés-táblákban nincs modellnév, és nincs tok/s vagy Forrás sor sem —
    # mindkettő elárulná, melyik oszlop a 8B (lassabb) és melyik a +RAG (van forrása).
    # (A fájl végi sebesség-összesítő oszloponként ad átlagot: kérdés-cellához nem
    # köthető, ezért nem old fel — a vizsgált rész a kérdés-blokkokra szűkül.)
    kerdes_blokk = md.split("## Dimenzió:", 1)[1].split("\n## Összesítő", 1)[0]
    for szivargas in ("szabi-8b", "szabi-3b", "tok/s", "Forrás"):
        assert szivargas not in kerdes_blokk, f"a vak kimenet elárulja: {szivargas}"
    assert rb.PONT_SOR in md and rb.OK_SOR in md


def test_decode_restores_labels_and_counts() -> None:
    plan = rb.build_blind_plan(_QK, ["szabi-8b", "szabi-3b"], set(), None, random.Random(7))
    md = rb.render_markdown(_TARGETS, _QK, _results(), rag=False, plan=plan, key_name="k.json")
    # „Kézi pontozás": a 8B mindenhol vállalható, a 3B nem (nyelv-hiba).
    pont_szerint = {"szabi-8b": ("1", ""), "szabi-3b": ("0", "nyelv")}
    sorok = []
    qid = None
    for line in md.splitlines():
        m = rb._QID_RE.match(line)
        if m:
            qid = m.group(1)
        if qid and line.startswith(f"| {rb.PONT_SOR} |"):
            betuk = sorted(plan[qid])
            line = rb._row([rb.PONT_SOR] + [pont_szerint[plan[qid][b]][0] for b in betuk])
        elif qid and line.startswith(f"| {rb.OK_SOR} |"):
            betuk = sorted(plan[qid])
            line = rb._row([rb.OK_SOR] + [pont_szerint[plan[qid][b]][1] for b in betuk])
        sorok.append(line)

    tmp = Path(__file__).with_name("_teszt_vak")
    tmp.mkdir(exist_ok=True)
    md_path, key_path, out_path = (tmp / "e.md", tmp / "k.json", tmp / "p.json")
    try:
        md_path.write_text("\n".join(sorok), encoding="utf-8")
        key_path.write_text(json.dumps({"kulcs": plan}), encoding="utf-8")
        report = rb.decode(md_path, key_path, None, out_path)
        pontok = report["pontok"]
        assert all(c["pont"] == 1 for c in pontok["szabi-8b"].values()), \
            "a vakítás után is a 8B-hez kell rendelni az 1-eseket"
        assert all(c["pont"] == 0 and c["ok"] == "nyelv"
                   for c in pontok["szabi-3b"].values())
        # A drift a KÖZÖS (label, kérdés) párokon mér — baseline-ként önmagát adva 100%.
        d = rb._drift(pontok, out_path)
        assert d["kozos_cellak"] == 4 and d["egyetertes"] == 1.0
    finally:
        for p in (md_path, key_path, out_path):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def test_decode_rejects_non_binary_score() -> None:
    md = "### id_01 — identitas\n\n|  | `A` |\n| --- | --- |\n| Pont (0/1) | 4 |\n"
    try:
        rb.parse_scored_markdown(md)
    except rb.BenchmarkError:
        return  # elvárt: a régi 1–5-ös pont nem csúszhat át bináriusnak
    raise AssertionError("a nem-bináris pontnak hibát kell dobnia")


def test_anchor_pick_is_stable_across_rounds() -> None:
    # A horgony csak akkor mér driftet, ha körről körre UGYANAZ az 5 kérdés jön.
    raw = {"meta": {"oszlopok": [{"label": "v10"}]},
           "eredmenyek": [{"id": f"q{i}", "valaszok": {"v10": _cella(f"v{i}")}}
                          for i in range(20)]}
    kerdesek = [{"id": f"q{i}", "dimenzio": "identitas", "kerdes": "?"} for i in range(20)]
    path = Path(__file__).with_name("_teszt_horgony.json")
    try:
        path.write_text(json.dumps(raw), encoding="utf-8")
        elso = rb.load_anchor(path, kerdesek, 5, None)
        masodik = rb.load_anchor(path, kerdesek, 5, None)
    finally:
        path.unlink(missing_ok=True)
    assert elso == masodik, "a horgony-válogatásnak determinisztikusnak kell lennie"
    assert len(elso[1]) == 5 and elso[0].startswith("⚓ ")


if __name__ == "__main__":
    test_timeout_degrades_and_run_continues()
    test_setup_error_still_hard_fails()
    test_blind_markdown_hides_model_identity()
    test_decode_restores_labels_and_counts()
    test_decode_rejects_non_binary_score()
    test_anchor_pick_is_stable_across_rounds()
    print("MIND ZÖLD")
