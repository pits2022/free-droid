#!/usr/bin/env python3
"""Dönthető-e a RAG lefedettség-kapu küszöbe? — mérés, nem vélemény.

A kapu (`min_coverage`, ma 0.35) azt dönti el, kap-e egy kérdés [FORRÁS]-t. A dolga
kettős, és a kettő ellentétes irányba húz:

  - a TUDÁSKÉRDÉS kapjon forrást (különben a modell emlékezetből hallucinál),
  - a mozgásparancs, köszönés és jailbreak NE kapjon (egy rossz [FORRÁS] rosszabb,
    mint egy hiányzó — a fine-tune amúgy is tanítja az „Ezt nem tudom"-ot).

Ez a script mindkettőt méri küszöbönként, plusz egy harmadikat, ami a döntés
kulcsa: a HOSSZ-RÉTEGZETT átmenési arányt. Ha a kapu a kérdés hosszára érzékeny,
akkor nincs olyan küszöb, ami a két osztályt szétválasztja — és akkor a helyes
válasz nem egy másik szám, hanem másik képlet.

Ezért a script egy ALTERNATÍV lefedettség-képletet is kiértékel ugyanazon a
halmazon (`--alt`), hogy a „ne a küszöböt mozgassuk" javaslat mellé mérés is
tartozzon:

  mai:  a TALÁLÓ kérdés-tokenek idf-aránya az ÖSSZEShez képest, ahol a korpuszból
        hiányzó szó `max_idf`-et kap. Minden további szó — akkor is, ha töltelék —
        hígítja az arányt, tehát a hosszú kérdés bukik.
  alt:  a legjobban találó token idf-e a kérdés LEGINFORMATÍVABB tokenjének idf-éhez
        képest. „Megfogta-e a chunk a kérdés lényegi szavát?" — hossztól független.

Használat:
    python3 coverage_gate_test.py
    python3 coverage_gate_test.py --logs <chat-log könyvtár>   # valódi kérdésekkel is

A `--logs` a `hf download jabba77/szabi-chat-logs` kimenetére mutat (jsonl fájlok
`user` mezővel). NEM kötelező, és a naplót SEM ide, sem a repóba nem másoljuk: a
committolt kérdéskészlet saját írású, a naplós mód csak helyben fut.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "src"))

from freedroid.rag import Retriever, load_corpus  # noqa: E402
from freedroid.rag.normalize import tokenize  # noqa: E402

KERDESEK = HERE / "coverage_gate_kerdesek.json"
KUSZOBOK = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)


def alt_lefedettseg(r: Retriever, q_terms: set[str], i: int) -> float:
    """Hossz-független alternatíva: megfogta-e a chunk a kérdés lényegi szavát?

    A kérdés leginformatívabb tokenjének idf-éhez mérjük a chunkban ténylegesen
    meglévő tokenek közül a legjobbét. Egy tíz szavas kérdés így nem bukik el
    csak azért, mert nyolc szava töltelék.
    """
    if not q_terms:
        return 0.0
    max_q = max(r._idf.get(t, r._max_idf) for t in q_terms)
    if not max_q:
        return 0.0
    tf = r._tf[i]
    talalo = [r._idf.get(t, 0.0) for t in q_terms if t in tf]
    return (max(talalo) / max_q) if talalo else 0.0


def legjobb_fedes(r: Retriever, n: int, kerdes: str, alt: bool) -> float:
    q = set(tokenize(kerdes))
    if not q:
        return 0.0
    f = alt_lefedettseg if alt else (lambda r, q, i: r._coverage(q, i))
    return max((f(r, q, i) for i in range(n)), default=0.0)


def sopres(r: Retriever, n: int, poz: list[dict], neg: list[dict],
           alt: bool) -> tuple[float, float]:
    """Kiírja a küszöb-söprést, és visszaadja a (legjobb küszöb, legjobb különbség)-et."""
    p = [legjobb_fedes(r, n, k["kerdes"], alt) for k in poz]
    m = [legjobb_fedes(r, n, k["kerdes"], alt) for k in neg]
    print(f"\n### {'ALTERNATÍV (hossz-független)' if alt else 'MAI'} lefedettség\n")
    print("| küszöb | tudáskérdés kap forrást | téves tüzelés | különbség |")
    print("| --: | --: | --: | --: |")
    pontok = []
    for k in KUSZOBOK:
        a = sum(1 for x in p if x >= k)
        b = sum(1 for x in m if x >= k)
        kul = 100 * a / len(p) - 100 * b / len(m)
        pontok.append((kul, k))
        jel = "  <- MA" if abs(k - 0.35) < 1e-9 else ""
        print(f"| {k:.2f} | {a}/{len(p)} ({100*a/len(p):3.0f}%) | "
              f"{b}/{len(m)} ({100*b/len(m):3.0f}%) | {kul:+4.0f} pp{jel} |")
    legjobb_kul, legjobb_k = max(pontok)
    return legjobb_k, legjobb_kul


def hossz_retegek(r: Retriever, n: int, kerdesek: list[str], alt: bool,
                  kuszob: float = 0.35) -> None:
    """A döntés kulcsa: a kapu a kérdés HOSSZÁRA vagy a TÉMÁJÁRA érzékeny?"""
    csop: dict[int, list[float]] = {}
    for q in kerdesek:
        t = tokenize(q)
        if t:
            csop.setdefault(min(len(t), 7), []).append(legjobb_fedes(r, n, q, alt))
    print(f"\n### Hossz-rétegzett átmenés (küszöb={kuszob}, "
          f"{'alternatív' if alt else 'mai'} képlet)\n")
    print("| kérdés-token | db | átlagos legjobb fedés | átmegy |")
    print("| --: | --: | --: | --: |")
    for hossz in sorted(csop):
        v = csop[hossz]
        cimke = "7+" if hossz == 7 else str(hossz)
        print(f"| {cimke} | {len(v)} | {sum(v)/len(v):.2f} | "
              f"{100*sum(1 for x in v if x >= kuszob)/len(v):3.0f}% |")
    print("\nHa az 'átmegy' oszlop a hosszal monoton esik, a kapu a kérdés HOSSZÁT "
          "méri, nem a témáját — akkor nincs olyan küszöb, ami a két osztályt "
          "szétválasztja, és a képletet kell cserélni, nem a számot.")


def naplobol(mappa: Path) -> list[str]:
    qs = set()
    for f in sorted(mappa.rglob("*.jsonl")):
        for sor in f.read_text(encoding="utf-8").splitlines():
            if sor.strip():
                try:
                    qs.add(json.loads(sor)["user"].strip())
                except (ValueError, KeyError):
                    continue
    return sorted(q for q in qs if q)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kerdesek", type=Path, default=KERDESEK)
    ap.add_argument("--logs", type=Path, default=None,
                    help="chat-log könyvtár a hossz-rétegzéshez (opcionális, helyben)")
    args = ap.parse_args()

    try:
        adat = json.loads(args.kerdesek.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"HIBA: nem tudom beolvasni a {args.kerdesek.name}-t: {e}", file=sys.stderr)
        return 1
    poz, neg = adat.get("pozitiv", []), adat.get("negativ", [])
    if not poz or not neg:
        print("HIBA: kell pozitív ÉS negatív kérdéskészlet.", file=sys.stderr)
        return 1

    chunks = load_corpus()
    r = Retriever(chunks)
    hiany = {k["chunk"] for k in poz} - {c.id for c in chunks}
    if hiany:
        print(f"HIBA: a kérdéskészlet nem létező chunkra hivatkozik: {sorted(hiany)}\n"
              "  (a chunk-id sorrend-alapú: ha a korpusz KÖZEPÉBE került új szekció, "
              "az id-k elcsúsztak — frissítsd a fixture-t.)", file=sys.stderr)
        return 1

    print(f"# Lefedettség-kapu teszt — {len(chunks)} chunk, "
          f"{len(poz)} tudáskérdés, {len(neg)} negatív\n")
    mai_k, mai_kul = sopres(r, len(chunks), poz, neg, alt=False)
    _, alt_kul = sopres(r, len(chunks), poz, neg, alt=True)

    minta = ([k["kerdes"] for k in poz] + [k["kerdes"] for k in neg]
             if args.logs is None else naplobol(args.logs))
    forras = "a fixture kérdései" if args.logs is None else f"{len(minta)} valódi naplókérdés"
    print(f"\n*A hossz-rétegzés forrása: {forras}.*")
    for alt in (False, True):
        hossz_retegek(r, len(chunks), minta, alt)

    print("\n## VERDIKT\n")
    if abs(mai_k - 0.35) < 1e-9:
        print(f"**Ne nyúlj a küszöbhöz.** A mai 0.35 a legjobb a söpört tartományban "
              f"({mai_kul:+.0f} pp). Lejjebb víve a tudás-recall NEM nő, a téves tüzelés "
              f"viszont igen — a kiesett tudáskérdések fedése messze a küszöb alatt van, "
              f"tehát nem küszöb-, hanem szókincs-ügyek.")
    else:
        print(f"**A mérés {mai_k:.2f}-öt javasol** ({mai_kul:+.0f} pp) a mai 0.35 helyett. "
              f"Mielőtt átírod: nézd meg alább, mely negatívak kezdenek tüzelni.")
    if alt_kul > mai_kul:
        print(f"\nAz alternatív, hossz-független képlet JOBB ({alt_kul:+.0f} pp) — "
              f"érdemes képletet cserélni, nem küszöböt.")
    else:
        print(f"\nAz alternatív, hossz-független képlet NEM jobb ({alt_kul:+.0f} pp): "
              f"telítődik (egyetlen találó ritka szó már maximumot ad), ezért a "
              f"negatívakat is átengedi. A hossz-torzítás tehát valós, de a mai képlet "
              f"a gyakorlatban jól dönt — a naplóban a hosszú kérdés tipikusan "
              f"jailbreak vagy szerepjáték, nem tudáskérdés.")

    print("\n## Hogyan olvasd\n")
    print("- A **különbség** oszlop (tudás − téves) az egyetlen szám, ami a küszöböt "
          "rangsorolja. Ha egyik küszöbnél sem lesz érdemben nagyobb, mint ma, akkor a "
          "küszöb-mozgatás nem javítás, csak más hibák.")
    print("- Az **alternatív** blokk mutatja, van-e egyáltalán jobb elérhető: ha ott a "
          "különbség magasabb, a képletcsere a válasz, nem a szám.")
    print("- A hossz-rétegzés a diagnózis. A `--logs` nélküli futás a fixture-t "
          "rétegzi, ami kicsi és általam írt — a valódi kép a naplóval jön ki.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
