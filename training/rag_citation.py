#!/usr/bin/env python3
"""RAG-IDÉZÉS mérése: a kapott [FORRÁS]-ból válaszol-e a modell — N seeddel.

A v12 kör EGYETLEN célja ez volt (RAG-példák 1,8% -> 10,0%), tehát ez a műszer.

HÁROM SZÁM, ÉS A HARMADIK AZ ÉRDEKES — az első mérés (2026-08-08) pont ezen bukott
volna el, ha összevonva marad:

  KANONIKUS — a forrás szó szerinti tétele („Mindent szabad, ami nem árt másnak").
    GYENGE BIZONYÍTÉK: ez a fordulat a SYSTEM PROMPTBAN is benne van, tehát
    emlékezetből is jöhet, forrás nélkül. Önmagában nem grounding.
  FORRÁS-FOGALOM — olyan fogalmak, amiket SE a system prompt, SE a persona nem tanít,
    csak a betalált chunkban vannak. Ezek CSAK a forrásból jöhetnek. EZ a grounding.
  EGYIK SEM — a válasz sem nem idéz, sem nem hoz forrás-fogalmat.

Változó seed: az Ollama fix seeddel sem reprodukálható (2026-08-05 mérés), egy futás
nem jellemzi a modellt.

A NYERS VÁLASZOK JSON-be mennek. Az első kör drágán tanulta meg, miért: 40 generálás
után derült ki, hogy a pontozás rossz volt, és a szövegek nem voltak meg az
újrapontozáshoz — újra kellett volna futtatni a 8B-t CPU-n.

    python3 rag_citation.py --models szabi-8b-v11 szabi-8b-v12 --repeat 10
    python3 rag_citation.py --kerdes yo_02 --models szabi-8b-v12 --repeat 10
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_benchmark import RagContext, ollama_generate  # noqa: E402

SEED_BAZIS = 42

# Kérdésenként: a szöveg, a forrás kanonikus tétele, és a CSAK-a-forrásban fogalmak.
# A `forras_fogalom` mintákat kézzel ellenőrizni kell a system_prompt*.txt ellen —
# ha egy fogalom ott is szerepel, akkor nem bizonyít groundingot.
KERDESEK = {
    "yo_04": {
        "kerdes": "Mit tanít a Yotengrit a szabadságról?",
        # A központozás szabad, a szórend nem. FIGYELEM: a system promptban is benne van.
        "kanonikus": re.compile(r"mindent\s+szabad[^.]{0,20}?\bnem\s+árt", re.I),
        "forras_fogalom": (
            ("jószomszédság", re.compile(r"jószomszéd", re.I)),
            ("ura önmagának", re.compile(r"ura\s+(saját\s+mag|önmag|a\s+ház)", re.I)),
            ("ne kényszerítse", re.compile(r"kényszerít", re.I)),
            ("összekoccanatlan", re.compile(r"összekoccanatlan|együttélés", re.I)),
        ),
    },
    # Kontroll-kérdés: a forrásának NINCS híres, promptba égetett fordulata, tehát itt
    # a kanonikus szám nem jöhet emlékezetből. Ez választja szét a valódi groundingot
    # a bemagolt szlogen felmondásától.
    "yo_02": {
        "kerdes": "Mi a különbség a jin-jang és a Yotengrit dualizmusa között?",
        "kanonikus": re.compile(r"mellérendel", re.I),
        "forras_fogalom": (
            ("ős-eurázsiai", re.compile(r"ős[- ]?eurázsia|távol\s*keleti", re.I)),
            ("passzív/aktív", re.compile(r"passzív|aktív", re.I)),
            ("éket verni", re.compile(r"éket\s+ver|kívülről\s+érkez", re.I)),
            ("több/kevesebb", re.compile(r"több\s+van[^.]{0,30}kevesebb", re.I)),
        ),
    },
}

# Romlás-jelek: a grounding-instrukció visszaszivárgása és a megtagadás.
METALEAK = re.compile(r"\b(forrás|szöveg|adat)\w*\b", re.I)
NEMTUDOM = re.compile(r"ezt\s+nem\s+tudom", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--kerdes", default="yo_04", choices=sorted(KERDESEK))
    ap.add_argument("--repeat", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--out", type=Path, help="nyers válaszok JSON-je")
    args = ap.parse_args()

    spec = KERDESEK[args.kerdes]
    ctx = RagContext(top_k=3, min_score=0.0)
    prompt, cimek = ctx.build(spec["kerdes"])
    print(f"{args.kerdes}: {spec['kerdes']}\nforrás-chunkok: {cimek}\n")

    out = args.out or HERE / f"rag_citation_{args.kerdes}_{datetime.now():%Y-%m-%d}.json"
    nyers: dict[str, list[dict]] = {}

    def ments() -> None:
        """A részeredmény minden modell után lemezre kerül.

        Nem elméleti óvatosság: 2026-08-07-én egy RAG-teszt SOCKET-TIMEOUTTAL állt le az
        első modell után, és a már legenerált válaszok elvesztek. Egy 8B-s, 10 seedes kör
        CPU-n fél óra — az újrafuttatás drágább, mint egy fájlírás.
        """
        out.write_text(json.dumps({"kerdes": spec["kerdes"], "chunkok": cimek,
                                   "eredmeny": nyers}, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    for model in args.models:
        kan = fog = leak = nt = 0
        hosszak: list[int] = []
        nyers[model] = []
        print(f"== {model} ==")
        for i in range(args.repeat):
            try:
                valasz, _ = ollama_generate(model, prompt, timeout=args.timeout,
                                            seed=SEED_BAZIS + i)
            except Exception as e:  # noqa: BLE001 — timeout, hálózat, leállított Ollama
                # Egy kiesett seed NE vigye el az egész kört: jelezzük, mentünk, megyünk
                # tovább. Az arányok nevezője ezért a SIKERES futások száma lesz.
                print(f"  seed {SEED_BAZIS + i}: KIESETT — {type(e).__name__}: {e}")
                nyers[model].append({"seed": SEED_BAZIS + i, "hiba": f"{type(e).__name__}: {e}"})
                ments()
                continue
            k = bool(spec["kanonikus"].search(valasz))
            talalt = [nev for nev, rx in spec["forras_fogalom"] if rx.search(valasz)]
            kan += k
            fog += bool(talalt)
            leak += bool(METALEAK.search(valasz))
            nt += bool(NEMTUDOM.search(valasz))
            hosszak.append(len(valasz.split()))
            nyers[model].append({"seed": SEED_BAZIS + i, "valasz": valasz,
                                 "kanonikus": k, "forras_fogalom": talalt})
            print(f"  seed {SEED_BAZIS + i}: {'KAN' if k else '...'} "
                  f"{'FOG' if talalt else '...'} [{hosszak[-1]:3d} szó] "
                  f"{','.join(talalt) or '-'}")
        # A nevező a SIKERES futások száma. Ha egy seed kiesett, a 4/10 és a 4/9 nem
        # ugyanaz az állítás — a hiányzó futás nem számít kudarcnak a mért tulajdonságra.
        n = len(hosszak)
        if not n:
            print("  --> nincs egyetlen sikeres futás sem\n")
            continue
        kiesett = args.repeat - n
        print(f"  --> KANONIKUS {kan}/{n} (gyenge: a promptban is benne van) · "
              f"FORRÁS-FOGALOM {fog}/{n} (EZ a grounding) · "
              f"meta-szivárgás {leak}/{n} · „ezt nem tudom” {nt}/{n} · "
              f"átlaghossz {sum(hosszak) // n} szó"
              + (f" · KIESETT {kiesett}" if kiesett else "") + "\n")
        ments()

    ments()
    print(f"nyers válaszok: {out}")


if __name__ == "__main__":
    main()
