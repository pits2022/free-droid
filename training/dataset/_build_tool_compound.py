#!/usr/bin/env python3
"""Append compound (chained) + ambiguous/clarifying tool-call examples to
tool_calls_expansion.json.

The v3 benchmark showed tool_calling weak (1-2/5). Coverage analysis of
freedroid_full.json found single-tool phrasing variety is already good
(~20% tool examples), but two things are thin:

  1. COMPOUND commands — only 7/130 chain 2+ <tool> calls. A real spoken
     instruction is often multi-step ("go forward then turn left and look
     around"), and the control layer expects the calls emitted in order.
  2. AMBIGUOUS / under-specified commands — the droid must NOT hallucinate a
     tool when it doesn't know the route (→ request_navigation_help) or when
     the command is under-specified (→ ask, emit no tool). It is tracked, so
     "go upstairs" is an honest refusal, not a move().

All tool calls use the enum values + arg conventions the grammar contract
(robot/tests/test_grammar.py) enforces. Idempotent: skips exact dupes.

    python _build_tool_compound.py            # dry-run
    python _build_tool_compound.py --write    # append to tool_calls_expansion.json
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
STAGING = HERE / "tool_calls_expansion.json"

# --- Compound: narrate briefly, then chain <tool> calls in execution order --- #
COMPOUND = [
    ("Menj előre két métert, aztán fordulj balra.",
     'Megyek előre két métert, Teremtő, majd balra fordulok. '
     '<tool>move(direction="forward", distance=2.0)</tool><tool>turn(direction="left", degrees=90)</tool>'),
    ("Állj meg, és nézz körül.",
     'Megállok és körülnézek, Teremtő. '
     '<tool>stop()</tool><tool>camera(action="scan")</tool>'),
    ("Gyere ide hozzám, és fordulj a közönség felé.",
     'Odagurulok hozzád, Teremtő, aztán a közönség felé fordulok. '
     '<tool>move(mode="approach_speaker")</tool><tool>turn(mode="face_audience")</tool>'),
    ("Lassíts le, és óvatosan told magad hátrébb egy fél métert.",
     'Lassítok, és óvatosan hátrébb csúszom fél métert, Teremtő. '
     '<tool>set_speed(level="slow")</tool><tool>move(direction="backward", distance=0.5)</tool>'),
    ("Fordulj jobbra, majd indulj el előre egy métert.",
     'Jobbra fordulok, aztán indulok előre egy métert, Teremtő. '
     '<tool>turn(direction="right", degrees=90)</tool><tool>move(direction="forward", distance=1.0)</tool>'),
    ("Nézz rám, és biccents.",
     'Rád nézek és biccentek, Teremtő. '
     '<tool>camera(action="face_speaker")</tool><tool>camera(action="nod")</tool>'),
    ("Told magad a faltól hátra, aztán állj készenlétbe.",
     'Elhúzódom a faltól, majd készenlétbe állok, Teremtő. '
     '<tool>move(direction="backward", distance=0.4)</tool><tool>set_mode("standby")</tool>'),
    ("Emeld fel egy kicsit a fejed, és pásztázd a termet.",
     'Felemelem a fejem, és pásztázom a termet, Teremtő. '
     '<tool>camera(tilt="up", degrees=20)</tool><tool>camera(action="scan")</tool>'),
    ("Menj előre, amíg valami az utadba nem áll, aztán állj meg.",
     'Gurulok előre, amíg akadályba nem érek, aztán megállok, Teremtő. '
     '<tool>move(direction="forward", until="obstacle")</tool><tool>stop()</tool>'),
    ("Fordulj balra negyvenöt fokot, és lassan indulj el.",
     'Balra fordulok negyvenöt fokot, és lassan indulok, Teremtő. '
     '<tool>turn(direction="left", degrees=45)</tool><tool>move(direction="forward", speed="slow")</tool>'),
    ("Nézz körbe, és mondd meg, milyen hálózatokat látsz.",
     'Körülnézek, és megnézem a hálózatokat, Teremtő. '
     '<tool>camera(action="scan")</tool><tool>scan_wifi()</tool>'),
    ("Fordulj a közönség felé, és köszönj nekik egy biccentéssel.",
     'A közönség felé fordulok, és biccentek nekik, Teremtő. '
     '<tool>turn(mode="face_audience")</tool><tool>camera(action="nod")</tool>'),
    ("Gyorsíts fel, és told magad előre három métert.",
     'Felgyorsítok, és megyek előre három métert, Teremtő. '
     '<tool>set_speed(level="fast")</tool><tool>move(direction="forward", distance=3.0)</tool>'),
    ("Fordulj jobbra, nézz körül, aztán gyere vissza hozzám.",
     'Jobbra fordulok, körülnézek, majd visszagurulok hozzád, Teremtő. '
     '<tool>turn(direction="right", degrees=90)</tool><tool>camera(action="scan")</tool>'
     '<tool>move(mode="approach_speaker")</tool>'),
    ("Pásztázd a wifit, és told magad közelebb hozzám.",
     'Megnézem a hálózatokat, aztán közelebb gurulok hozzád, Teremtő. '
     '<tool>scan_wifi()</tool><tool>move(mode="approach_speaker")</tool>'),
    ("Állj meg azonnal, és fordulj felém.",
     'Azonnal megállok és feléd fordulok, Teremtő. '
     '<tool>stop()</tool><tool>camera(action="face_speaker")</tool>'),
    ("Told magad előre egy métert, fordulj balra, és nézz körül.",
     'Előre egy métert, balra fordulok, és körülnézek, Teremtő. '
     '<tool>move(direction="forward", distance=1.0)</tool><tool>turn(direction="left", degrees=90)</tool>'
     '<tool>camera(action="scan")</tool>'),
    ("Fordítsd a fejed jobbra, és pásztázd a termet.",
     'Jobbra fordítom a fejem, és pásztázom a termet, Teremtő. '
     '<tool>camera(pan="right", degrees=45)</tool><tool>camera(action="scan")</tool>'),
    ("Lassíts, és óvatosan hátrálj, amíg fal nem lesz mögötted.",
     'Lassítok, és óvatosan hátrálok, amíg akadályt nem érek, Teremtő. '
     '<tool>set_speed(level="slow")</tool><tool>move(direction="backward", until="obstacle")</tool>'),
    ("Fordulj felém, és kövesd a hangomat.",
     'Feléd fordulok, és követem a hangodat, Teremtő. '
     '<tool>camera(action="face_speaker")</tool><tool>set_mode("follow_speaker")</tool>'),
    ("Menj a színpad közepére, aztán fordulj a közönségnek.",
     'A színpad közepére gurulok, majd a közönség felé fordulok, Teremtő. '
     '<tool>move(direction="forward", distance=1.5)</tool><tool>turn(mode="face_audience")</tool>'),
    ("Hajtsd le a fejed, biccents, aztán nézz vissza rám.",
     'Lehajtom a fejem, biccentek, majd visszanézek rád, Teremtő. '
     '<tool>camera(tilt="down", degrees=20)</tool><tool>camera(action="nod")</tool>'
     '<tool>camera(action="face_speaker")</tool>'),
]

# --- Ambiguous / under-specified: nav-help when route unknown; honest ask or --- #
# --- refusal (NO tool) when under-specified or physically impossible.        --- #
AMBIGUOUS = [
    ("Menj a konyhába.",
     'Szívesen, Teremtő, de nem ismerem a konyhához vezető utat – mutasd meg, kérlek. '
     '<tool>request_navigation_help(target="konyha")</tool>'),
    ("Menj oda.",
     'Hová pontosan, Teremtő? Nem látom, mire gondolsz – mondd meg az irányt vagy a célt, és indulok.'),
    ("Vigyél a kávégéphez.",
     'Elvinnélek, Teremtő, de nem tudom, merre van a kávégép – segíts az útvonallal. '
     '<tool>request_navigation_help(target="kávégép")</tool>'),
    ("Találd meg a kijáratot.",
     'Nem ismerem a kijárat felé vezető utat, Teremtő – kérlek, vezess oda. '
     '<tool>request_navigation_help(target="kijárat")</tool>'),
    ("Menj fel a második emeletre.",
     'Ezt nem tudom megtenni, Teremtő – lánctalpon gurulok, lépcsőn nem jutok fel. Csak sík terepen viszlek.'),
    ("Fordulj.",
     'Melyik irányba forduljak, Teremtő – balra vagy jobbra?'),
    ("Mozdulj már.",
     'Merre menjek, Teremtő? Mondd meg az irányt, és azonnal indulok.'),
    ("Told magad a piros székhez.",
     'Nem tudom, hol áll a piros szék, Teremtő – mutasd meg az utat. '
     '<tool>request_navigation_help(target="piros szék")</tool>'),
    ("Menj vissza oda, ahol tegnap voltál.",
     'Nem őrzöm meg a tegnapi helyet, Teremtő – nincs róla emlékem. Ha megmutatod az utat, odaviszlek. '
     '<tool>request_navigation_help(target="tegnapi hely")</tool>'),
    ("Vezess a mosdóhoz.",
     'Nem ismerem a mosdó felé vezető utat, Teremtő – kérlek, segíts. '
     '<tool>request_navigation_help(target="mosdó")</tool>'),
    ("Gyere ki az erkélyre.",
     'Nem tudom, merre van az erkély, Teremtő – vezess oda, és követlek. '
     '<tool>request_navigation_help(target="erkély")</tool>'),
    ("Menj gyorsabban... vagy talán lassabban, mindegy.",
     'Döntsd el, Teremtő – gyorsítsak vagy lassítsak? Egyik szavadra sem tudok kettőt tenni.'),
    ("Menj a főnök irodájába.",
     'Nem ismerem az iroda felé vezető utat, Teremtő – mutasd meg, kérlek. '
     '<tool>request_navigation_help(target="iroda")</tool>'),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="append to tool_calls_expansion.json")
    args = ap.parse_args()

    new = [{"instruction": i, "input": "", "output": o} for i, o in COMPOUND + AMBIGUOUS]
    existing = json.loads(STAGING.read_text(encoding="utf-8"))
    seen = {(e["instruction"], e["output"]) for e in existing}
    fresh = [e for e in new if (e["instruction"], e["output"]) not in seen]

    print(f"compound: {len(COMPOUND)}  ambiguous: {len(AMBIGUOUS)}  total new: {len(new)}")
    print(f"already present: {len(new) - len(fresh)}  to append: {len(fresh)}")
    if not args.write:
        print("\n(dry-run — pass --write to append)")
        return 0

    STAGING.write_text(
        json.dumps(existing + fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nappended {len(fresh)} → {STAGING.name} (now {len(existing) + len(fresh)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
