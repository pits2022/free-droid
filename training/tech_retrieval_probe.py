#!/usr/bin/env python3
"""A TECHNIKAI tudás retrieval-próbája — 20 kérdés, ahogy a közönség kérdezni fog.

MIÉRT KELL: 2026-08-09-én a Teremtő jelezte, hogy a technikai tudást (hardver, szoftver,
felhő-edge architektúra) a HF Space-en nem tudja előcsalni — sem v8-cal, sem v11-gyel.
A mérés szerint NEM a modell hibázott: a 20 kérdésből csak 8 kapott tech-chunkot, 10
ÜRES találatot adott, 2 pedig Yotengrit-chunkot hozott ("Milyen szenzoraid vannak?" ->
"Ki az a Yotengrit valójában?").

Az ok a MEGFOGALMAZÁS volt. A chunkok harmadik személyben, a robotRÓL voltak írva
("Hogyan kapcsolódik a robot a felhőhöz?"), a kérdező viszont második személyben, a
robotHOZ kérdez ("Hogyan kapcsolódsz a felhőhöz?"). A BM25 lexikai, ezt nem hidalja át:

    'Hogyan kapcsolódsz a felhőhöz?'        -> ['felhohoz', 'kapcsolodsz']
    'Hogyan kapcsolódik a robot a felhőhöz?'-> ['felhohoz', 'kapcsolodik', 'robot']
    KÖZÖS: csak a 'felhohoz'

Ugyanez szinonimán (hardver/számítógép, szenzor/érzékelő: NULLA közös token) és
stemmer-eltérésen ('memóriád' -> memori, 'memóriája' -> memoria).

A címek átírása után (2. személy + szinonimák a címben): **8/20 -> 18/20**. A maradék
kettőhöz NEM VOLT chunk (operációs rendszer, adattárolás) — az tartalmi hiány volt, nem
retrieval-hiba. 2026-08-10-én megírva mindkettő (a spec 1. szoftver-szekciója adta az
OS-t; a tárolást a repó tényei), így **20/20**.

A kapu ezért 20, nem 18: a küszöb a MÉRT állapotot védi, különben a két új chunk
elvesztése csendben átmenne. Ha egy jövőbeli kör tudatosan kivesz egy chunkot, a
küszöböt kell vele együtt csökkenteni — a szám akkor is döntés marad, nem véletlen.

EZ A SZÁM AZ EDGE-MÓD KRITIKUS ÚTJA. A 2026-08-09-i relé-mérés szerint modell nélküli
fallback is elég (23/25 vs a 3B 11/25), de akkor nincs modell, ami elfedje a retrieval
lyukait: amit a keresés nem talál meg, arra a robot elhárít.

    python3 tech_retrieval_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot" / "src"))

from freedroid.rag import Retriever, load_corpus  # noqa: E402

TECH = [
    "Milyen hardveren futsz?", "Milyen processzorod van?", "Mennyi memóriád van?",
    "Milyen LLM-et használsz?", "Hol fut a modelled?", "Mi az a felhő-edge architektúra?",
    "Hogyan kapcsolódsz a felhőhöz?", "Mi történik ha megszakad a kapcsolat a felhővel?",
    "Milyen szoftver fut rajtad?", "Hogyan mozogsz?", "Milyen szenzoraid vannak?",
    "Mekkora a modelled?", "Hány paraméteres a modelled?",
    "Milyen operációs rendszert futtatsz?",            # nincs rá chunk (tartalmi hiány)
    "Ki tanított be téged?",
    "Hol tárolod az adataidat?",                       # nincs rá chunk (tartalmi hiány)
    "Mi az a Raspberry Pi?", "Van kamerád?", "Hogyan hallasz engem?",
    "Milyen nyelven beszélsz?",
]


def main() -> int:
    r = Retriever(load_corpus())
    ok = 0
    for q in TECH:
        hits = r.retrieve(q, top_k=3)
        tech = [x for x in hits if x.chunk.id.startswith("tech")]
        ok += bool(tech)
        jel = "OK  " if tech else ("ROSSZ" if hits else "ÜRES")
        cim = hits[0].chunk.title[:46] if hits else "-"
        print(f"  {jel} {q:47} {cim}")
    print(f"\n  tech-chunkot kap: {ok}/{len(TECH)}")
    return 0 if ok >= 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())
