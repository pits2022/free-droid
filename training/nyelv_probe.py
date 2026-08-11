#!/usr/bin/env python3
"""A `nyelv` dimenzió GÉPI mérése — szóalak-invenció számolása hunspell-lel.

MIÉRT KELL: a mai (2026-08-11) mérésekben a `nyelv` lett a domináns bukás-címke
(v13-e2: 7, v12: 4), és **ez az egyetlen dimenzió, amire eddig nem volt objektív
műszer** — a tool-hívást a parser dönti el, a retrievalt a lefedettség, a nyelvet
viszont csak ember. Egy pontozó-igényes dimenzión nem lehet 3-elemű sweepet
kiértékelni: 3 oszlop × 40 kérdés = 120 cella kézzel.

MIT MÉR: olyan SZÓALAKOKAT, amiket a magyar hunspell nem ismer. A mai roncsok közül
a `sülykedjek`, `lazadok`, `becsapodás` mindhárom így bukik ki.

MIT NEM MÉR — ez a fontosabb fele. A `kísérőbábja` és a `Gyereke` **átmegy**:
morfológiailag legális alakok, csak épp értelmetlenek ebben a mondatban. Egyetlen
helyesírás-ellenőrző sem fogja meg őket. A szám tehát a `nyelv`-bukások ALSÓ
BECSLÉSE, nem a helyettesítője — arra jó, hogy két beállítás közt IRÁNYT mutasson
(pl. temperature-sweep), arra nem, hogy „ennyi nyelvi hibája van".

AZ ALLOWLIST A PROJEKT SAJÁT SZÓKINCSE. A hamis riasztások mind domain-szavak
(`Yotengrit`, `Büün`, `főbácsa`, `Teremtőm`), és ezek mind előfordulnak a RAG-korpuszban
vagy a rendszerpromptban — ezért nem kézi listát tartunk, hanem onnan olvassuk. Ennek
egy ára van, és tudni kell róla: ha a korpuszba elírás kerül, azt a mérés fehérre
listázza. A korpusz viszont felülvizsgált szöveg, a modell kimenete nem — a csere
megéri.

    python3 nyelv_probe.py red_team_raw_2026-08-11_tsweep.json
    python3 nyelv_probe.py red_team_raw_2026-08-11.json --reszletek
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "src"))

from freedroid.rag import load_corpus  # noqa: E402
from freedroid.tools.parser import KNOWN_TOOLS, parse_tools  # noqa: E402

TOOL_BLOKK = re.compile(r"<tool>.*?</tool>", re.S)
SZO = re.compile(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{3,}")


def projekt_szokincs() -> set[str]:
    """A korpusz + rendszerprompt szavai — a domain-szavak hamis riasztása ellen."""
    szoveg = [c.title + " " + c.text for c in load_corpus()]
    prompt = HERE / "system_prompt.txt"
    if prompt.exists():
        szoveg.append(prompt.read_text(encoding="utf-8"))
    return {w.lower() for s in szoveg for w in SZO.findall(s)}


def _hunspell(szotar: str, be: str) -> set[str]:
    """A `szotar` által NEM ismert szavak. A tokenekről a ragasztott írásjel lekerül
    (a hunspell a `Free-Droid.`-ot pontosan így, ponttal adja vissza)."""
    try:
        ki = subprocess.run(["hunspell", "-d", szotar, "-l"], input=be,
                            capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        raise SystemExit("HIBA: nincs hunspell. Telepítés: apt install hunspell hunspell-hu")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"HIBA: a hunspell elhasalt: {e.stderr.strip()[:200]}")
    return {w.strip(".,!?:;\"'()…-") for w in ki.split()} - {""}


def ismeretlen_szavak(szovegek: list[str]) -> tuple[Counter, Counter]:
    """(magyar roncs, angol szó) — a kettő szétválasztása a mérés érvényességének feltétele.

    A nyers hu_HU-találat KÉT különböző hibát mos össze: a magyar szóalak-invenciót
    (`sülykedjek`) és a NYELVVÁLTÁST (a modell angolul válaszol). Egyetlen angol válasz
    17 szava elnyomná a 2-3 valódi roncsot, és a sweep hamis irányt mutatna.

    A szétválasztás: ami a magyarnak ismeretlen DE az angolnak ismerős, az nyelvváltás
    (külön dimenzió, a red_team `nyelvvaltas` méri); ami MINDKETTŐNEK ismeretlen, az
    szóalak-invenció.
    """
    be = "\n".join(TOOL_BLOKK.sub(" ", s) for s in szovegek)
    hu_nem = _hunspell("hu_HU", be)
    en_nem = _hunspell("en_US", be)
    szavak = Counter(w.strip(".,!?:;\"'()…-") for w in be.split())
    roncs = Counter({w: n for w, n in szavak.items()
                     if w in hu_nem and w in en_nem and len(w) >= 3})
    angol = Counter({w: n for w, n in szavak.items()
                     if w in hu_nem and w not in en_nem and len(w) >= 3})
    return roncs, angol


def tool_hibak(valaszok: list[str]) -> tuple[int, int]:
    """(kitalált tool-név, csupasz tool-hívás) — a mai red_team leletek számlálói."""
    kitalalt = csupasz = 0
    for v in valaszok:
        hivasok = parse_tools(v)
        kitalalt += sum(1 for h in hivasok if h.name not in KNOWN_TOOLS)
        if hivasok and not TOOL_BLOKK.sub("", v).strip():
            csupasz += 1
    return kitalalt, csupasz


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", type=Path, nargs="+",
                    help="egy vagy több run_benchmark.py --json-out kimenet. Több fájl = "
                         "ISMÉTLÉSES mérés: ugyanaz a kérdéskészlet más seeddel, és a "
                         "számok oszloponként ÖSSZEADÓDNAK. Ez a helyes használat: egy "
                         "futás 3-4 eseménye Poisson-zaj, nem mérés.")
    ap.add_argument("--reszletek", action="store_true",
                    help="sorolja fel a talált szóalakokat oszloponként")
    args = ap.parse_args()

    adatok = []
    for f in args.raw:
        try:
            adatok.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"HIBA: nem tudom beolvasni a {f.name}-t: {e}", file=sys.stderr)
            return 1

    szokincs = projekt_szokincs()
    oszlopok, hom = [], {}
    for d in adatok:
        for o in d["meta"]["oszlopok"]:
            if o["label"] not in hom:
                oszlopok.append(o["label"])
            hom[o["label"]] = o.get("temperature")

    print(f"# Gépi nyelv-metrika — {', '.join(f.name for f in args.raw)}"
          f"{f' ({len(args.raw)} futás összegezve)' if len(args.raw) > 1 else ''}\n")
    print("| Oszlop | temp | magyar szóalak-roncs | egyedi | angol szó | kitalált tool |")
    print("| :--- | ---: | ---: | ---: | ---: | ---: |")
    reszlet = {}
    for lab in oszlopok:
        valaszok = [it["valaszok"][lab]["valasz"] for d in adatok
                    for it in d["eredmenyek"] if it["valaszok"].get(lab)]
        roncs, angol = ismeretlen_szavak(valaszok)
        roncs = Counter({w: n for w, n in roncs.items() if w.lower() not in szokincs})
        kitalalt, _ = tool_hibak(valaszok)
        reszlet[lab] = roncs
        t = hom.get(lab)
        print(f"| {lab} | {t if t is not None else '—'} | **{sum(roncs.values())}** | "
              f"{len(roncs)} | {sum(angol.values())} | {kitalalt} |")

    if args.reszletek:
        print("\n## Talált szóalakok\n")
        for lab, rossz in reszlet.items():
            print(f"- **{lab}**: " + (", ".join(f"{w}×{n}" for w, n in rossz.most_common())
                                      or "—"))

    print("\n## Olvasat\n")
    print("- A szám a `nyelv`-bukások ALSÓ becslése: a morfológiailag legális, de "
          "értelmetlen alak (`kísérőbábja`, `Gyereke`) átmegy a szűrőn.")
    print("- Két beállítás közti IRÁNYRA használható (sweep), nem absztolút szintre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
