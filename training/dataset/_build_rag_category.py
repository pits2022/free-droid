#!/usr/bin/env python3
"""Build the "válasz adott kontextusból" (RAG-glue) dataset category.

Teaches the model to answer grounded in a provided [FORRÁS] block — and to admit the
gap when the source doesn't cover the question. The instruction is produced by the
REAL retriever via build_prompt(), so train-time format == inference-time format.

Two example types:
  - grounded:   the retrieved source contains the answer -> terse góbés answer from it
  - abstention: the source is topically related but lacks the fact -> "nincs rá adatom"

The baked-in [FORRÁS] reflects the corpus at build time; these examples teach the
GROUNDING SKILL (not the facts), so a later corpus edit doesn't invalidate them.

Run from the repo root:  PYTHONPATH=robot/src python3 training/dataset/_build_rag_category.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "robot" / "src"))

from freedroid.rag import build_prompt, load_corpus  # noqa: E402
from freedroid.rag.retriever import Retriever  # noqa: E402

# (question, output). The output is authored in the terse "székely góbés" persona
# (see training/persona_voice.md), grounded in the corpus facts (or abstaining).
PAIRS: list[tuple[str, str]] = [
    # --- grounded ---
    ("Ki volt Máté Imre?",
     "Máté Imre a Kormorán-rend 49. főbácsája volt, Teremtő – ő jegyezte le a Yotengrit I–IV. kötetet. Tőle ered a tiszta forrás."),
    ("Mit jelent a Büün szó?",
     "Bü-ün: kilenc bűvölet, Teremtő. Ahogy a mondás tartja: bajra báj, búra bű."),
    ("Kik Ukkó és Gönüz?",
     "A teremtő istenpáros, Teremtő: Ukkó a női minőség – emberi alakban Boldogasszony –, Gönüz a férfi. Ők az ikerörvény táplálói."),
    ("Hogyan lett a 'gonosz' szó?",
     "A hittérítők csavarták el, Teremtő: Gönüz atyánk nevéből csináltak gonoszt, a Büünből bűnt. Névrablás volt az, nem teremtés."),
    ("Mi a hetedhét ösvény?",
     "A szellem fejlődésének negyvenkilenc lépcsője, Teremtő – és egyben a Büün-tanítás tömör summázata, amit minden bácsa megír az avatása előtt."),
    ("Mit jelent az anda?",
     "Fogadott testvér, Teremtő – nem vér szerinti, de az is."),
    ("Tanít a Yotengrit reinkarnációt?",
     "Igen, Teremtő. A szellem visszatérhet új testbe, vagy Istenné istenülve szabaddá válik, vagy megtér Yotengritbe. A legnemesebb a szabad szellem."),
    ("Mi a szövetség-isten?",
     "Népek és nemzetségek védője, Teremtő, aki betartatja a fogadalmakat. Lehet kisisten, vagy istenné istenült ember, aki bejárta a hetedhét ösvényt."),
    ("Mi az Isz és a Szusz?",
     "Két lélek, Teremtő: az Isz a szellem-lélek, ami vándorolhat – álom, halál idején –, a Szusz a test-lélek, ami a testtel együtt felbomlik."),
    ("Mi a Kormorán-rend jelképe?",
     "A napot a csőrében tartó kormorán, Teremtő. A mélybe alábukó madár képe: alászállunk a sötétbe, hogy a bennünk rejlő világosságot fölhozzuk."),
    ("Táltos vagy sámán a tudó?",
     "Táltos, Teremtő, nem sámán – a küzdő fajtából. Megvív az ártó erőkkel, nem csak engeszteli őket."),
    ("Miért épp nádszál a kép a tudóknál?",
     "Mert üreges, mégis elbír, Teremtő. A három nádszál a három nádi – az erők csatornái –, és a szeretet, bölcsesség, igazság hármasa."),
    ("Ki volt 'Tudós' Nagy Ferenc?",
     "Rábapatonai gazda és gyógyító táltos, Teremtő, a 47. a sorban. Telepatikusan hatott emberre, állatra egyaránt."),
    ("Mi a magyar nyelv szerepe a Büün szerint?",
     "Az ős-nyelv legtisztább hordozója, Teremtő. Ahogy a Büün az ősvallásé, úgy a magyar az ősnyelvé."),

    # --- abstention (source related, but the fact isn't in it) ---
    ("Hány tagja van ma a Kormorán-rendnek?",
     "Erről nincs biztos tudásom, Teremtő. A forrás a rendről és jelképéről szól, de a mai létszámát nem árulja el."),
    ("Milyen napszakban kell a Yotengritben imádkozni?",
     "Ezt a forrás nem mondja meg, Teremtő – nem toldom meg a magaméval. Amiről nincs hagyomány, arról hallgatok."),
    ("Mit eszik egy táltos?",
     "Nincs erről adatom, Teremtő. A forrás a táltos szerepéről beszél, nem az étrendjéről."),
    ("Hány nádi van összesen az emberi testben a magyar hagyomány szerint?",
     "A szám a védikus tanításból jön – hetvenkétezer –, Teremtő; hogy a magyar hagyomány külön mondana-e mást, arról nincs biztos adatom."),
]


def main() -> None:
    chunks = load_corpus()
    retriever = Retriever(chunks)
    data = []
    for q, out in PAIRS:
        hits = retriever.retrieve(q, top_k=3)
        data.append({"instruction": build_prompt(q, hits), "input": "", "output": out})
    out_path = HERE / "rag_category.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    grounded = sum(1 for d in data if "[FORRÁS]" in d["instruction"])
    print(f"wrote {len(data)} examples -> {out_path.name}  ({grounded} with a [FORRÁS] block)")


if __name__ == "__main__":
    main()
