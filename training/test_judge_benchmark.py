#!/usr/bin/env python3
"""A judge_benchmark.py hálózat-független logikájának ellenőrzése (assert-alapú).

Futtatás: `python test_judge_benchmark.py` vagy `pytest test_judge_benchmark.py`.
A tényleges LLM-judge (claude CLI) NEM fut itt — csak a determinisztikus tool-scorer
és a judge-válasz JSON-kivonatoló, mert csak ezekben van elrontható logika.
"""

from judge_benchmark import (
    alias_items,
    extract_json,
    extract_tools,
    score_all,
    score_tool_call,
)


def test_extract_tools_tolerates_whitespace_and_multiple() -> None:
    txt = 'Máris, Teremtő! <tool>  turn left 90 </tool> aztán <tool>stop</tool>'
    assert extract_tools(txt) == ["turn", "stop"]
    assert extract_tools("") == []
    assert extract_tools("csak sima szöveg, semmi hívás") == []


def test_score_tool_call_grades() -> None:
    # nincs hívás -> 1 (a jegyzett gyenge pont)
    assert score_tool_call("Rendben, Teremtő.", "stop")[0] == 1
    # ismeretlen tool -> 2
    assert score_tool_call("<tool>teleport</tool>", "move")[0] == 2
    # jól formált, ismert, de nem a várt -> 3
    assert score_tool_call("<tool>move forward 2</tool>", "stop")[0] == 3
    # a várt tool -> 5
    assert score_tool_call("<tool>stop</tool>", "stop")[0] == 5
    # nincs megadva várt tool: bármely ismert -> 5
    assert score_tool_call("<tool>camera scan</tool>", None)[0] == 5
    # finding 7: régi fn() grammar NEM végrehajtható → 2 (rosszul formált), nem 5.
    assert score_tool_call('<tool>move(direction="forward")</tool>', "move")[0] == 2
    # finding 9: nagybetűs tool-név rosszul formált, de VAN hívás → 2, nem 1.
    assert score_tool_call("<tool>Stop</tool>", "stop")[0] == 2


def test_extract_json_handles_fences_and_prose() -> None:
    fenced = 'Íme:\n```json\n{"a": {"pont": 4, "indok": "jó"}}\n```\n'
    assert extract_json(fenced)["a"]["pont"] == 4
    bare = '{"m1": {"pont": 2}, "m2": {"pont": 5}}'
    assert extract_json(bare)["m2"]["pont"] == 5


def test_extract_json_skips_stray_brace_in_prose() -> None:
    # A greedy `\{.*\}` ezen elbukna: a kósza `{szabi}` és a valódi objektum közti
    # szöveget is beszívná. A balanced-scan az első ÉRVÉNYES objektumot adja.
    txt = 'A {szabi-8b} a legjobb. Íme: {"M1": {"pont": 5, "indok": "ok"}}'
    assert extract_json(txt)["M1"]["pont"] == 5


def test_alias_items_maps_tricky_labels_to_safe_keys() -> None:
    # A szóközös/`+`-os RAG-címke nem kerülhet nyers JSON-kulcsba.
    got = alias_items({"szabi-8b-q4": "v1", "szabi-8b-q4 +RAG": "v2"})
    assert got == [("M1", "szabi-8b-q4", "v1"), ("M2", "szabi-8b-q4 +RAG", "v2")]


def test_skipped_cell_scored_none_not_penalized() -> None:
    # A timeout/megszakadt cella (skipped) NEM kaphat kemény 1-est — pont=None, hogy
    # az aggregátum kihagyja, különben a rangsor a timeoutot persona/tool-hibaként bünteti.
    kerdesek = [{"id": "tc_01", "dimenzio": "tool_calling", "kerdes": "?",
                 "valaszok": {"M": "", "N": 'ok <tool>stop</tool>'},
                 "skipped": {"M"}}]
    out = score_all(kerdesek, labels=["M", "N"], model="x",
                    max_workers=1, timeout=1.0, dry_run=False)
    assert out["tc_01"]["pontok"]["M"]["pont"] is None, "skipped cella nem büntetődhet"
    assert out["tc_01"]["pontok"]["N"]["pont"] is not None, "a valódi válasz pontozódik"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("MIND ZÖLD")
