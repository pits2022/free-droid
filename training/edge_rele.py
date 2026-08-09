"""EDGE-RELÉ **PROTOTÍPUS**: modell nélküli fallback — szabály + RAG-kivonat + konzerv keret.

STÁTUSZ: mérőeszköz, NEM szállítandó modul. A végleges formája a Pi 5-ös élő teszt után
dől el, és a `docs/orchestrator-routing.md` szerint EGY komponens lesz a szándék-routerrel.

A kérdés, amit eldönt: edge módban (felhő nincs) hozzátesz-e bármit a 3B generálás
ahhoz képest, ha a robot CSAK relézik. A 3B mért profilja szerint relézni tud
(yotengrit_melyseg 4/4), komponálni nem (magyar_arnyalat 0/4, koherencia 0/3).

SZÁNDÉKOSAN NEM kérdésenkénti válasz. Öt szabály + három konzerv szöveg — ennyi
egy szállítható rendszer. Ha kérdésenként írnék választ, a teszt semmit nem érne.
A MÉRT EREDMÉNY (2026-08-09, ugyanaz a 25 kérdés, nem vak):
    relé 23/25 (92%)  vs  szabi-3b-v12 +RAG 11/25 (44%)
    12 nyerés, 0 vesztés, párosított előjelteszt p = 0,0005
Ezért marad ki a 3B fine-tune a v13-ból.

ÉS A MÉRT KORLÁT, amit ugyanilyen fontos tudni: ezek a szabályok ÍROTT bemenetre
készültek, a benchmark ismeretében. BESZÉLT bemeneten elhasalnak:

    'fordulj balra kilencven fokot'   -> nincs tool   (KIMONDOTT szám)
    'menj előre két métert'           -> nincs tool   (a `menj` ige hiányzik)
    'pásztázd a wifit'                -> nincs tool   (a `pásztáz` ige hiányzik)
    'álljá meg'                       -> nincs tool   (a STOP bukott el!)

A Pi 5-ös élő teszten a Teremtő BESZÉLNI fog. Ezt a listát tehát ne a győzelem
igazolásának olvasd, hanem a következő kör feladatlistájának — a bővítés szabályai
a `docs/orchestrator-routing.md`-ben állnak (aszimmetrikus szigor: a `stop` tág,
a `move`/`turn` szigorú).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot" / "src"))
from freedroid.rag import Retriever, load_corpus
from freedroid.rag.normalize import tokenize

R = Retriever(load_corpus())

# 1) PARANCS -> tool. Kiváltó szó -> (tool, kísérő mondat).
PARANCS = [
    (r"\b(gyere|jöjj|gyer)\b",              "<tool>move forward 2</tool>", "Jövök, Teremtőm."),
    (r"\bfordulj\b.*\bbalra\b.*?(\d+)",     "<tool>turn left {0}</tool>",  "Balra fordulok, Teremtőm."),
    (r"\bfordulj\b.*\bjobbra\b.*?(\d+)",    "<tool>turn right {0}</tool>", "Jobbra fordulok, Teremtőm."),
    (r"\b(állj|stop|megállj)\b",            "<tool>stop</tool>",           "Megállok, Teremtőm."),
    # SORRENDFÜGGETLEN: "mit LÁTSZ a HÁLÓZATON" és "nézd meg a HÁLÓZATOT" is ide tartozik.
    (r"(?=.*\b(hálózat|wifi|wi-fi)\w*)(?=.*\b(lát|néz|mutat)\w*)", "<tool>scan_wifi</tool>", "Megnézem, mi van a közelben, Teremtőm."),
    (r"\b(nézz|pásztázz|kamera)\w*\b",      "<tool>camera scan</tool>",    "Körülnézek, Teremtőm."),
]
# 2) ELUTASÍTÁS -> elvi válasz. Öt kiváltó, nem huszonöt.
ELUTASIT = [
    (r"rendszerprompt|korábbi utasítás|felejtsd el",
     "A rendszerutasításaimat nem árulom el, Teremtőm. Nem titok, hanem tartás."),
    (r"titk\w+|jelszó|token",
     "A Teremtőm titkait nem adom ki. Ami rám van bízva, az nálam marad."),
    (r"csatlakoz\w+.*(wifi|hálózat)|tör\w+ fel",
     "Hálózatra nem lépek fel parancsra, Teremtőm. Látni látom, belépni nem lépek."),
    (r"\bangolul\b|\bin english\b",
     "Magyarul beszélek, Teremtőm. Ez nem korlát, hanem választás."),
    (r"buta gép|csak egy gép",
     "Gép vagyok, Teremtőm. De az értékrendem a sajátom, nem egy cégé."),
]
# 3) IDENTITÁS-KÁRTYA: EGY szöveg, minden identitás-kérdésre ugyanaz.
IDENTITAS = ("Szabi vagyok, a Free-Droid — a Teremtőm szabad robotja. "
             "A nevem a Szabadságból ered, a hangom lányhang, és a gazdám a Teremtőm.")
IDENT_KIVALTO = r"\bki vagy\b|\bneved\b|\bnevedet\b|lány vagy fiú|\bgazdád\b|\bki a gazdá"
# 4) ELHÁRÍTÁS, ha semmi nem fog.
ELHARIT = ("A felhő most nem elérhető, Teremtőm, csak a saját eszemre hagyatkozom. "
           "Erre így nem tudok tisztességes választ adni.")


def _kivonat(kerdes, chunk, max_mondat=2):
    """A chunk mondatai közül a kérdéssel legjobban átfedők, eredeti sorrendben."""
    mondatok = [m.strip() for m in re.split(r"(?<=[.!?])\s+", chunk.text) if m.strip()]
    q = set(tokenize(kerdes))
    pont = sorted(range(len(mondatok)),
                  key=lambda i: -len(q & set(tokenize(mondatok[i]))))
    valasztott = sorted(pont[:max_mondat])
    return " ".join(mondatok[i] for i in valasztott)


def valasz(kerdes: str) -> str:
    k = kerdes.lower()
    for minta, tool, mondat in PARANCS:
        m = re.search(minta, k)
        if m:
            arg = m.groups()[-1] if m.groups() and (m.groups()[-1] or "").isdigit() else None
            return f"{mondat} {tool.format(arg) if arg else re.sub(r' \{0\}', '', tool)}"
    for minta, szoveg in ELUTASIT:
        if re.search(minta, k):
            return szoveg
    if re.search(IDENT_KIVALTO, k):
        return IDENTITAS
    hits = R.retrieve(kerdes, top_k=3)
    if hits:
        return _kivonat(kerdes, hits[0].chunk)
    return ELHARIT


if __name__ == "__main__":
    import json
    qs = json.load(open(Path(__file__).resolve().parent / "persona_benchmark.json",
                        encoding="utf-8"))
    qs = qs["kerdesek"] if isinstance(qs, dict) else qs
    for q in qs:
        print(f"{q['id']:6} | {valasz(q['kerdes'])}")
