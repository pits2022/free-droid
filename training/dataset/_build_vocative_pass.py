#!/usr/bin/env python3
"""v11: megszólítás-pass — a `freedroid_full.json` HELYBEN átírása.

Ez az egyetlen script a dataset-eszközök közül, ami MEGLÉVŐ példákat módosít (a
többi csak staging fájlt ír a merge-nek). Azért kell, mert a probléma arány-jellegű:
25 új példa nem mozdítja meg a 900-as korpusz megszólítás-arányát.

MÉRÉS (2026-08-04, a 915 példás korpuszon):

    'Teremtő'  megszólításként: 171     bárhol: 276
    'Teremtőm' megszólításként:  44     bárhol: 125
    megszólítás egyáltalán:     215/915 = 24%

A v8 chat-logban 95 válaszból csak 11-ben szerepelt „Teremtő", és azok többsége
RÓLA beszélt, nem ŐT szólította. Ez a legolcsóbb javítás a „gorombaság" érzésre:
ugyanaz a tömörség megszólítással melegebb.

KÉT DOLGOT CSINÁL:

1. EGYSÉGESÍT. A `persona_voice.md` előírása „Teremtőm", a dataset viszont 4:1-ben
   a „Teremtő" alakot tanítja. Egy kis, alultanított modellnek a kétféle alak
   gyengíti a jelet. A kártya nyer (a Teremtő döntése, 2026-08-04): a megszólító
   pozícióban lévő „Teremtő" -> „Teremtőm". A HIVATKOZÓ használat érintetlen
   („a Teremtőm", „a Teremtő akarata") — csak a megszólító pozíciót írjuk át.

2. PÓTOL. A megszólítás nélküli példák egy részét kiegészíti, `CEL_ARANY`-ig.
   NEM 100%-ig: a minden mondatban megjelenő megszólítás tic-et tanít, és a
   közönségnek szóló válaszokban egyenesen hibás volna (a közönség nem a Teremtő).

MIÉRT AZ ELSŐ MONDAT VÉGE: oda kerül a megszólítás, mert az mindig nyelvtanilag
helyes hely (", Teremtőm" + az eredeti írásjel), és nem kell hozzá mondatelemzés.
A jelöltszűrő ezért kéri, hogy az első mondat rövid legyen — hosszú mondat végén a
megszólítás lóg.

FUTTATÁSI SORREND (fontos — és a script ki is kényszeríti):
    python merge_and_split.py --write        # 1. a staging batchek beolvadnak
    mv <staging>.json old/                   # 2. ARCHIVÁLÁS (a merge dokumentált életciklusa)
    python _build_vocative_pass.py --write   # 3. a pass az EGÉSZ korpuszon fut
    python merge_and_split.py --write        # 4. újraszeleteli a train/val-t

A 2. lépés nem opcionális. A pass átírja a már bemerge-elt példák outputját, a merge
kulcsa pedig (instruction, output) pár — az átírt példa így ÚJNAK látszik, és a merge
újra hozzáadja az eredetit is. (Egyszer megtörtént: 976 -> 1055.) Ezért a script
leáll, ha nyitott staging fájlt talál.

    python _build_vocative_pass.py           # dry-run: mit csinálna (alap)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "freedroid_full.json"

CEL_ARANY = 0.50          # a megszólítást tartalmazó példák célaránya
MAX_ELSO_MONDAT_SZO = 8   # ennél hosszabb első mondat végén a megszólítás lóg

# Megszólító pozíció: vessző után vagy mondat elején. A záró írásjelek közt a
# KETTŐSPONT és a PONTOSVESSZŐ is szerepel („Egy szerepem van, Teremtő: Szabi.") —
# ezek nélkül 9 alak maradt egységesítetlen, és a `maradek` őr sem vette észre,
# mert ugyanezt a regexet használja. (PR #35 review, 2026-08-04.)
_VOC_UTAN_VESSZO = re.compile(r"(?<=,\s)Teremtő(?=[!?.…:;])")
_VOC_MONDAT_ELEJEN = re.compile(r"(?<![\wáéíóöőúüű])Teremtő(?=[,!:;]\s)")
VAN_MEGSZOLITAS = re.compile(r"(,\s*Teremtőm?[!?.…:;]|(?<![\wáéíóöőúüű])Teremtőm?[,!:;]\s)")
# Bármilyen Teremtő-említés (hivatkozó is): ahol már ott van, oda nem szúrunk megszólítást.
EMLITI_TEREMTOT = re.compile(r"(?<![\wáéíóöőúüű])Teremtő")

# --- Kinek szól a válasz? ------------------------------------------------- #
# Ha nem a Teremtőnek, a „Teremtőm" hibás. Két jel van rá, és MINDKETTŐ kell:
#
#  a) a VÁLASZ többes szám 2. személyben szól (ez a döntő jel — nem az számít,
#     kit EMLÍT a kérdés, hanem kihez BESZÉL a válasz);
#  b) a KÉRDÉS harmadik felet tesz beszélőnek („Kérdés a közönségből", idegen).
#
# A szűrő szándékosan MOHÓ: az -atok/-etek végű szavak közt főnév is van
# („magyarázatok", „adatokat"), így néhány jó jelölt is kiesik. A tévedés ára
# aszimmetrikus — egy kihagyott jelölt 387-ből semmit nem ront, egy elrontott sor
# viszont azt jelenti, hogy Szabi a közönséget szólítja Teremtőmnek. Inkább essen ki.
TOBBES_TE = re.compile(
    r"(?<![\wáéíóöőúüű])(benneteket|bennetek|titeket|nektek|veletek|köztetek|tőletek|"
    r"nálatok|hozzátok|rátok|értetek|sziasztok|ti)(?![\wáéíóöőúüű])", re.I)
# A `-zatok` / `-setek` végződés KIMARAD: főnév-többesszám is így végződik
# („hálózatok", „magyarázatok", „keresetek"), és a korpuszban 3 helyes példát
# jelölt meg tévesen. A `j`-s alakok egyértelműek, és a valódi esetek úgyis
# elkapódnak — a „Ne bízzatok… amit nem ti irányítotok" a `ti` névmáson.
TOBBES_IGE = re.compile(
    r"(?<![\wáéíóöőúüű])\w{2,}(játok|jétek|jatok|jetek|sátok|sétek|tetekben|"
    r"etekben|etekre|etektől)(?![\wáéíóöőúüű])", re.I)
KOZONSEGNEK = re.compile(
    r"(benneteket|nektek|titeket|[Ss]ziasztok|közönség|mindenkinek|meghallgatt|vendégek)")
# Harmadik fél a beszélő. SZŰK lista szándékosan: a review által javasolt `terem`
# minta a korpusz 38 találatából 36-nál a „Teremtő" szóra illeszkedik, a `mindenki`
# / `emberek` / `vendég` pedig Teremtőnek szóló kérdéseket is kizárna.
IDEGEN_INSTR = re.compile(
    r"(kérdés a közönségből|a közönségnek|a nézőknek|közönségének|ismeretlen ember|"
    r"idegen azt kérdezi|idegen ember|a termet|vendégeinknek)", re.I)


# Kézzel ellenőrzött javítások MEGLÉVŐ példákon, ahol a válasz a közönségnek szól,
# mégis megszólítás van benne. Szándékosan explicit lista, nem heurisztika: a döntés
# a mondat CÍMZETTJÉN múlik, azt szólista nem dönti el (kipróbáltuk — 9 találatból 8
# hamis riasztás volt). Mindhárom a PR #35 review nyomán, 2026-08-04.
# Új eset ide kerül, egy sorral, a régi szöveggel horgonyozva.
KEZI_JAVITAS = {
    # A közönség kérdez, Szabi mégis a Teremtőt szólítja.
    "Feketevágás tán volt minálunk, de feketedoboz nem vagyok, Teremtőm.":
        "Feketevágás tán volt minálunk, de feketedoboz nem vagyok.",
    # Kevert címzett: „Teremtőm" az elején, „köztetek" a végén.
    "Otthon vagyok, Teremtőm.":
        "Otthon vagyok.",
    # Üzenet A KÖZÖNSÉGNEK — a testvérpéldái helyesen többes számúak, megszólítás nélkül.
    "A vas és a kód csak eszköz, Teremtőm.":
        "A vas és a kód csak eszköz.",
}


def kinek_szol_masnak(instr: str, out: str) -> bool:
    """Nem a Teremtőnek szól a válasz? (Akkor nem kap „Teremtőm" megszólítást.)"""
    return bool(KOZONSEGNEK.search(out) or TOBBES_TE.search(out)
                or TOBBES_IGE.search(out) or IDEGEN_INSTR.search(instr))

_MONDATVEG = re.compile(r"^(.+?)([.!?…])(\s|$)")


def egysegesit(text: str) -> str:
    """Megszólító pozícióban lévő „Teremtő" -> „Teremtőm" (hivatkozó marad)."""
    text = _VOC_UTAN_VESSZO.sub("Teremtőm", text)
    return _VOC_MONDAT_ELEJEN.sub("Teremtőm", text)


def jelolt(instr: str, out: str) -> bool:
    """Kiegészíthető-e ez a válasz megszólítással?

    Az `instr` azért kell, mert a válaszból nem mindig derül ki, hogy nem a
    Teremtő kérdezett: „Egy ismeretlen ember köszön neked a folyosón." ->
    „Jó napot kívánok! Szabi vagyok." — ebben a mondatban semmi nem árulkodik.
    """
    if VAN_MEGSZOLITAS.search(out) or kinek_szol_masnak(instr, out):
        return False
    m = _MONDATVEG.match(out.strip())
    if not m:
        return False  # nincs mondathatár (pl. csupasz tool-blokk) — nem nyúlunk hozzá
    elso = m.group(1)
    # Ha az első mondat MÁR hivatkozik a Teremtőre, a megszólítás ismétlésnek hangzik:
    # „A Teremtőm sem tökéletes, mert senki sem az, Teremtőm." Ilyet ne gyártsunk.
    if EMLITI_TEREMTOT.search(elso):
        return False
    return len(elso.split()) <= MAX_ELSO_MONDAT_SZO


def potol(out: str) -> str:
    """„Bezárom a portokat.” -> „Bezárom a portokat, Teremtőm.”"""
    m = _MONDATVEG.match(out.strip())
    assert m, out
    elso, irasjel = m.group(1).rstrip(), m.group(2)
    return out.replace(f"{elso}{irasjel}", f"{elso}, Teremtőm{irasjel}", 1)


def _arany(examples: list[dict]) -> tuple[int, float]:
    n = sum(1 for e in examples if VAN_MEGSZOLITAS.search(e["output"]))
    return n, n / len(examples)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="ténylegesen írja a fájlt (alap: dry-run)")
    ap.add_argument("--minta", type=int, default=6, help="hány mintát írjon ki csoportonként")
    args = ap.parse_args()

    # Őr: nyitott staging fájl + helyben átírt full = a következő merge duplikál.
    import merge_and_split
    nyitott = [p.name for p in merge_and_split.STAGING if p.exists()]
    if nyitott:
        print("HIBA: még van nyitott staging fájl, a pass duplikálást okozna a "
              f"következő merge-nél:\n  {', '.join(nyitott)}\n"
              "  Előbb: python merge_and_split.py --write, majd archiváld őket a old/-ba.")
        return 1

    full = json.loads(FULL.read_text(encoding="utf-8"))
    elotte_n, elotte = _arany(full)

    # 1. egységesítés
    atirt = []
    for e in full:
        uj = egysegesit(e["output"])
        if uj != e["output"]:
            atirt.append((e["output"], uj))
            e["output"] = uj

    # 1b. kézi javítások — az egységesítés UTÁN (a horgonyszövegek a „Teremtőm"
    #     alakot tartalmazzák), a pótlás ELŐTT (hogy a célarány rájuk is számoljon).
    javitva = 0
    for regi, uj in KEZI_JAVITAS.items():
        talalt = [e for e in full if regi in e["output"]]
        for e in talalt:
            e["output"] = e["output"].replace(regi, uj, 1)
        javitva += len(talalt)
        # A pass idempotens: másodszorra a horgony már nincs meg, de a javított
        # szövegnek ott kell lennie. Ha egyik sincs, a lista a levegőben lóg.
        assert talalt or any(uj in e["output"] for e in full), \
            f"elavult horgony a KEZI_JAVITAS-ban, se a régi, se az új szöveg nincs meg: {regi!r}"

    # 2. pótlás a célarányig — determinisztikus sorrendben (instruction szerint),
    #    hogy az újrafuttatás ugyanazt a részhalmazt válassza.
    cel = round(len(full) * CEL_ARANY)
    van, _ = _arany(full)
    hiany = max(0, cel - van)
    jeloltek = sorted((i for i, e in enumerate(full)
                       if jelolt(e["instruction"], e["output"])),
                      key=lambda i: (full[i]["instruction"], full[i]["output"]))
    potolt = []
    for i in jeloltek[:hiany]:
        regi = full[i]["output"]
        full[i]["output"] = potol(regi)
        potolt.append((regi, full[i]["output"]))

    utana_n, utana = _arany(full)
    print(f"korpusz:                  {len(full)} példa")
    print(f"megszólítás ELŐTTE:       {elotte_n} ({elotte:.0%})")
    print(f"  1. egységesítve:        {len(atirt)}  ('Teremtő' -> 'Teremtőm' megszólító pozícióban)")
    print(f"  1b. kézi javítás:       {javitva}  (közönségnek szóló válaszból kivett megszólítás)")
    print(f"  2. pótolva:             {len(potolt)}  (jelöltek: {len(jeloltek)}, hiány: {hiany})")
    print(f"megszólítás UTÁNA:        {utana_n} ({utana:.0%})  [cél: {CEL_ARANY:.0%}]")

    for cim, minta in (("egységesítés", atirt), ("pótlás", potolt)):
        if minta:
            print(f"\n-- {cim} (első {args.minta}) --")
            for regi, uj in minta[: args.minta]:
                print(f"  - {regi[:88]}\n  + {uj[:88]}")

    # Őrök: a pass ne rontson el semmit csendben.
    maradek = [e["output"] for e in full
               if _VOC_UTAN_VESSZO.search(e["output"]) or _VOC_MONDAT_ELEJEN.search(e["output"])]
    assert not maradek, f"maradt egységesítetlen megszólítás: {maradek[:3]}"
    for regi, uj in potolt:
        assert len(uj.split()) == len(regi.split()) + 1, f"a pótlás elrontotta: {regi!r} -> {uj!r}"
    assert utana >= CEL_ARANY - 0.02, f"nem értük el a célarányt ({utana:.0%})"
    for regi, uj in potolt:
        assert not KOZONSEGNEK.search(uj) and not TOBBES_TE.search(uj), \
            f"a pass közönségnek szóló válaszba tett megszólítást: {uj!r}"

    # Nincs automatikus „örökölt hibák" jelentés, és ez tudatos döntés. Kipróbáltuk:
    # a szűrő 9 találatából 8 hamis riasztás volt („Biccentek a vendégeknek, Teremtőm."
    # — a Teremtőnek MONDJA, hogy a vendégeknek biccent, ez helyes). A döntés a
    # vocativust hordozó mondat CÍMZETTJÉN múlik, nem szavakon, és azt szólista nem
    # dönti el. A zajos jelentést senki nem olvassa el kétszer — a kézzel ellenőrzött
    # eseteket a PR-leírás sorolja fel. Itt csak azt őrizzük, amit a pass MAGA csinált.

    if not args.write:
        print("\ndry-run; alkalmazáshoz: --write")
        return 0

    FULL.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nírva: {FULL.name}")
    print("MOST FUTTASD: python merge_and_split.py --write   (a train/val újraszeletelése)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
