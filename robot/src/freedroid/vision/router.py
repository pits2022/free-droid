"""Kell-e képkocka ehhez a kérdéshez.

Determinisztikus kulcsszó-illesztés, NEM osztályozó és NEM tool. A döntés az
orchestrátoré (spec §3/3. döntés): a mért tool-gyengeség (kitalált `action` értékek,
hiányzó irány) így nem tud elrontani semmit, és a `KNOWN_TOOLS` változatlan marad.

🔴 A MÉRT SZABÁLY, amit követ: ALKOTÁS-KÉRÉS ÉS PARANCS NE KAPJON KONTEXTUST. A
RAG-nál ez mérésből jött (a „Szabi, gyere ide!" mindhárom mintájában elveszett a
<tool> blokk, és a modell képességet hallucinált, amint hosszpadlót kapott). Ugyanez
áll a látásra: egy parancsra elküldött képkocka 2-3 másodpercet visz el a semmiért.

A kulcsszavak ÉS a kérdés UGYANAZON a tokenizálón mennek át — a közös tokenizáló
ékezetet/kis-nagybetűt normalizál és stopszót dob. DE: a `normalize.MIN_STEM = 6`
azt jelenti, hogy a `lát`/`néz` igecsalád SOHA nem kap tövezést (a stemmer csak
akkor vág, ha a maradék tő ≥ 6 karakter — a "lát"/"néz" 3-4 karakteres alapalak
erre sosem éri el a küszöböt). Egy agresszívebb tövező ezt megoldaná, de az a
RAG-index tövezését is módosítaná, amivel ez a tokenizáló KÖZÖS — kicsapná a
precizitást, amit PR #25 mérve kalibrált. A gyakori ragozott alakokat ezért
SZÁNDÉKOSAN, egyenként soroljuk fel lent — egy új alak hozzáadása új felszíni
alak felvételét jelenti, nem egy általánosabb szabályt.

🔴 EGY TOVÁBBI CSAPDA (mérve, javítva): egy kulcsszó-KIFEJEZÉS TÖBB szóból is
állhat ("nézz körül", "milyen színű"). Ha a kifejezés tokenjeit egyetlen lapos
halmazba öntjük, a szavaknak nem kell EGYÜTT szerepelniük a kérdésben — ezért
"Menj körbe a szoba körül!" (parancs) hamis pozitívot adott a `korul` token
miatt, "Nézz utána, mikor van a szünet!" pedig a `nezz` miatt (idiomatikus
"nézz utána", nem vizuális). A javítás: `_VISION_TOKEN_SETS` kifejezésenként
EGY token-halmazból áll (egy elem = egy kifejezés tokenjei), és egy kérdés csak
akkor talál, ha VALAMELYIK kifejezés ÖSSZES tokenje jelen van a kérdésben
(részhalmaz-illesztés) — nem elég, ha csak egy token metsz.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from freedroid.rag.normalize import tokenize, words

# SZŰK lista, szándékosan. Bővíteni csak úgy szabad, hogy a
# `test_a_parancsok_es_alkotas_keresek_NEM` teszt zöld marad: egy hétköznapi tő
# („van", „ez") bekerülése MINDEN kérdést látás-kérdéssé tenne.
#
# A `lát` igecsalád ragozott alakjai (lát, látod, látsz, látja, látni, láttál)
# KÜLÖN sorok, mert a MIN_STEM=6 miatt a közös tokenizáló ezeket sosem vonja
# össze — lásd a modul docstringjét.
#
# A CSUPASZ "lát" ugyanezért tüzel lore-kérdésre is, pl. "Mit jelent, hogy lát a
# lélek?" — ugyanaz a vállalt kompromisszum, mint a "milyen színű"-nél lent, csak
# itt a leírás NEM csak LATENCIA kérdés: egy képkocka ekkor egy NEM látás-kérdésre
# is elhagyja az eszközt (felmegy a felhős VLM-hez), ami adatvédelmi dimenzió, nem
# csak elvesztegetett 2-3 másodperc.
#
# "kit látsz" NINCS itt: a tokenjei ({"kit", "latsz"}) valódi szuperhalmaza a
# "látsz" kifejezés tokenjének ({"latsz"}) — bármely kérdés, amit a "kit
# látsz" elkapna, a "látsz" egyetlen tokenje is elkapja (ellenőrizve
# `tokenize()`-zal), tehát a külön sor felesleges.
#
# "nézd meg" SZÁNDÉKOSAN hiányzik: "nézd meg a kijelzőn" nem látás-kérdés, a
# kifejezés valódi kétértelmű — a kihagyás tudatos, nem hiányosság.
#
# "milyen színű" MARAD, bár lore-kérdésre is tüzelhet ("Milyen színű a
# Yotengrit zászlaja a mondák szerint?") — vállalt kompromisszum: a
# konferencia-közönségtől jövő "milyen színű" kérdés túlnyomó többsége valódi
# látás-kérdés, és a brief a "Milyen színű a pólóm?"-ot kötelező pozitívként
# írja elő. FIGYELEM: a "milyen" itt NEM védi a kifejezést a fenti egy-tokenes
# csapdától — "milyen" stopszó (`normalize.py`), tehát a kifejezés a tokenizáláson
# ténylegesen EGYETLEN tokenre (`szinu`) esik össze, nem kettőre.
#
# A csupasz "hányan" KIVÉVE (I-review, mérve 2026-09-09): egyetlen token, tehát
# BÁRMELY számláló lore-kérdésre tüzel, nem csak a jelenlévőkre — mérve:
#   "Hányan laknak Magyarországon?"      -> True (lore, HAMIS pozitív)
#   "Hányan képviselik a törzset?"       -> True (lore, HAMIS pozitív)
# Ez adatvédelmi kérdés, nem csak elvesztegetett idő: egy közönség-képkocka megy
# fel a felhőbe egy olyan kérdésre, aminek semmi köze a jelenlévőkhöz. A csere:
# páros kifejezések, hogy a többszavas illesztés védje őket — egyik társtoken
# (`vagytok`/`vannak`/`vagyunk`) sem stopszó, tehát mindkét token megmarad
# tövezés után.
#
# 🔴 A SPEC LISTÁJÁBÓL KÉT TAGOT SZÁNDÉKOSAN KIHAGYTUNK (I5, végső review) — ne
# vedd fel őket "a spec szerint":
#   - "ki van előtted" / "mi van előtted": az "előtted" ÖNMAGÁBAN egyetlen tokenre
#     tövez (`elotted`), és ez a token szuperhalmazként illeszkedne a "Fordulj az
#     előtted lévő fal felé!" PARANCSRA is — pont az az osztály, amit a router
#     kizárni hivatott (ld. a modul tetején, RAG-mérésre hivatkozva).
#   - "mi ez": a `tokenize()` ÜRES listát ad rá (mindkét szó stopszó) — a
#     részhalmaz-illesztésben egy üres tokenhalmaz MINDEN kérdésre illeszkedik
#     (`set() <= barmi`), tehát ez a kifejezés MINDEN kérdést látás-kérdésnek
#     jelölne. Lásd `_ellenorzi_uresek_ellen()` lent — ez a csapda importkor
#     hangosan bukik, nem csendben.
_LATAS_KIFEJEZESEK = (
    "látsz",
    "látod",
    "látni",
    "lát",
    "látja",
    "láttál",
    "nézz körül",
    "milyen színű",
    "hányan vagytok",
    "hányan vannak",
    "hányan vagyunk",
    # 🔴 STT-torzítások (élő menet, 2026-09-15, a transcript szó szerint): a Whisper a
    # „Mit látsz?"-t így hallotta — „Mitlát!", „Mit látze?", „Mondel mit Lats.", „Meet
    # lads!". Ezek a körök [LÁTVÁNY] nélkül mentek, és a modell kitalálta, mit lát —
    # pontosan a 2026-08-28-i konfabulációs út. A „lads" angol szó, tehát egy angol
    # mondatra („Hi lads!") is képet kér: vállalt ár, mert a robot csak magyarul
    # beszél, és a kihagyás itt hazugságot szül, a téves képkérés csak 3 másodpercet.
    # A forrásnál (a Whisper szótár-promptjában) is javítható — az mérendő, mert
    # hangfelvétel nélkül nem ellenőrizhető; ez a lista addig is fogja a mért alakokat.
    "mitlát",
    "látze",
    "látza",
    "lats",
    "lads",
)

# Hálózati „látás" — ha a kérdés ezek bármelyikét tartalmazza, NEM kér képet, akármi más
# illeszkedik. Mérve 2026-09-15: „Mit látsz a hálózaton?" és „…milyen hálózatokat látsz a
# Wi-Fi-n" a `látsz` miatt képet kért, és a robot a wifik helyett a szobát írta le (a
# Teremtő: „a router ezt szűrje ki"). Ugyanaz a részhalmaz-illesztés, mint a látás-listán
# (PR #136 review 4): a `Wi-Fi` két tokenje (`wi`, `fi`) PÁRBAN kell — egy magányos `wi`
# bármilyen rövid STT-maradék lehet —, és egy jövőbeli többszavas tiltókifejezés („helyi
# hálózat") sem tüzel egyetlen szavára. A rövid, kötőjel NÉLKÜL ragozott alakokra
# (`wifit`, `wifire`, `ssidet`, `ssidt`, `wlant` — nem tövezhetők, MIN_STEM) a
# `_is_network_question` előtag-illesztése felel (PR #136 review 6: az `ssid` és a
# `wlan` ugyanúgy átcsúszott, mint korábban a `wifi`). Ami előtaggal fogható, az CSAK
# ott szerepel (PR #136 review 7) — a kifejezéslista a tövezendő és a többtokenes elemeké.
_NETWORK_EXPRESSIONS = ("hálózat", "Wi-Fi")
_NETWORK_PREFIXES = ("wifi", "ssid", "wlan")


def _ellenorzi_uresek_ellen(kifejezesek: Sequence[str],
                            tokenek: Sequence[Collection[str]],
                            context: str = "látás") -> None:
    """I7 (végső review): a részhalmaz-illesztésben egy ÜRES tokenlistájú kifejezés
    (`set() <= barmi`) MINDEN kérdésre illeszkedne.

    A kár a listától függ, ezért a `context` a hibaüzenetben (PR #136 review 5): a
    látás-listán minden kérdés képet kérne, a hálózati tiltólistán a látás csendben
    megszűnne. Ma egyik kifejezés sem üres — de a spec saját "kell-e kép" listája
    TARTALMAZZA a "mi ez"-t, ami `tokenize()`-on üresre esik (mindkét szó stopszó). Ez a
    hívás importkor fut, tehát a hiba egy NEVEZETT `ValueError`, nem tizenegy rejtélyesen
    piros teszt."""
    # `strict=True`: eltérő hosszúságnál a sima `zip` a rövidebbnél némán megállna, és a
    # maradék kifejezést sosem ellenőrizné (PR #136 review 3 — pont ez történt az `ssid`-del).
    for kifejezes, tok in zip(kifejezesek, tokenek, strict=True):
        if not tok:
            raise ValueError(
                f"vision.router ({context}): {kifejezes!r} üres tokenlistára tövez — a "
                f"részhalmaz-illesztésben ez minden kérdésre tévesen illeszkedne")


def _build_token_sets(expressions: Sequence[str], context: str) -> tuple[frozenset[str], ...]:
    """Kifejezésenként EGY token-halmaz (egy elem tokenjei EGYÜTT kellenek), importkor
    ellenőrizve. Építés és ellenőrzés egy helyen: a kifejezés- és a halmazlista így
    szerkezetileg nem csúszhat szét (PR #136 review 5)."""
    token_sets = tuple(frozenset(tokenize(k)) for k in expressions)
    _ellenorzi_uresek_ellen(expressions, token_sets, context)
    return token_sets


_VISION_TOKEN_SETS = _build_token_sets(_LATAS_KIFEJEZESEK, "látás")
# 🔴 A tiltó oldalon a csapda FORDÍTVA ugyanaz (PR #136 review 2): egy üresre eső
# kifejezés (`frozenset() <= barmi`) MINDEN kérdést hálózatinak jelölne — és a látás
# csendben megszűnne.
_NETWORK_TOKEN_SETS = _build_token_sets(_NETWORK_EXPRESSIONS, "hálózat")


def _is_network_question(question: str, tokens: set[str]) -> bool:
    """Hálózati „látás" — ilyenkor SOHA nincs kép (a Teremtő, 2026-09-15).

    Az előtag a kötőjel NÉLKÜLI nyers szavakon fut, nem a tokeneken (PR #136 review 8):
    a „Wi-Fit"/„Wi-Fire" tokenje `wi` + `fit`, amit sem a `Wi-Fi` pár, sem a `wifi`
    előtag nem fogna — a `wifit` nyers alak viszont igen. A `tokens` a hívóé: a kérdést
    egyszer tokenizáljuk (PR #136 review 9)."""
    return (any(token_set <= tokens for token_set in _NETWORK_TOKEN_SETS)
            or any(w.replace("-", "").startswith(_NETWORK_PREFIXES) for w in words(question)))


@dataclass(frozen=True)
class Station:
    """A nézési terv egy állomása. `None` szög = maradjon az aktuális póz; `None` címke =
    a sor címke nélkül kerül a `[LÁTVÁNY]` blokkba (spec §3.4/5)."""

    label: str | None = None
    pan_deg: float | None = None
    tilt_deg: float | None = None

    def __post_init__(self) -> None:
        # A két szög EGYÜTT van vagy EGYÜTT hiányzik: a végrehajtó a `pan_deg`-ből dönti el,
        # kell-e póz, és a `move_to` mindkettőt várja. Egy félig megadott póz hangosan
        # bukjon, ne csendben maradjon ki a tilt (PR #137 review).
        if (self.pan_deg is None) != (self.tilt_deg is None):
            raise ValueError("Station: a pan_deg és a tilt_deg együtt adandó meg (vagy egyik sem)")


# Körbenézés — a „nézz körül" már a látás-kifejezések közt van; ezek a TÖBB-állomásos ág.
_LOOK_AROUND_PHRASES = ("nézz körül", "nézz körbe", "nézz szét", "nézzél körül",
                        "nézzél szét", "pásztázz körbe")
_LOOK_AROUND_TOKEN_SETS = _build_token_sets(_LOOK_AROUND_PHRASES, "körbenézés")

# 🔴 Az irány a stopszó-szűrés ELŐTTI szavakon dől el: a „fel" és a „le" STOPSZÓ, a
# `tokenize("nézz fel")` és a `tokenize("nézz le")` egyaránt `['nezz']` (mérve,
# 2026-09-15). A nyers szavakat a `rag.normalize.words()` adja, nem egy második ékezetfosztó.
_LOOK_VERBS = frozenset({"nezz", "nezzel"})
_DIRECTION_WORDS = {
    "up": frozenset({"fel", "felfele", "plafonra", "mennyezetre"}),
    "down": frozenset({"le", "lefele", "foldre", "padlora"}),
    "left": frozenset({"balra"}),
    "right": frozenset({"jobbra"}),
    # „Nézz előre" VISSZAHOZZA a fejet (PR #137 review): az egyirányú póz a válasz után
    # megmarad, és egy következő „nézz előre" nélküle a plafont írná le újra.
    "forward": frozenset({"elore", "szembe"}),
}
# Az irányszó legfeljebb ennyi szóval követheti az igét: „nézz kérlek a földre", de
# „Nézz rám és írd le" NEM lefelé nézés.
_DIRECTION_WINDOW = 3
# ...és közvetlenül MEGELŐZHETI (PR #137 review): a magyar fókuszpozíció természetes —
# „Balra nézz", „A földre nézz". Csak EGY szó: „Írd le és nézz rám" így sem lefelé nézés.
_DIRECTION_BEFORE = 1


def _direction(question: str) -> str | None:
    raw = words(question)
    for i, word in enumerate(raw):
        if word not in _LOOK_VERBS:
            continue
        nearby = raw[max(0, i - _DIRECTION_BEFORE):i] + raw[i + 1:i + 1 + _DIRECTION_WINDOW]
        for candidate in nearby:
            for direction, direction_words in _DIRECTION_WORDS.items():
                if candidate in direction_words:
                    return direction
    return None


def vision_plan(question: str, *, side_deg: float = 45.0, up_deg: float = 30.0,
                down_deg: float = 30.0) -> tuple[Station, ...] | None:
    """A kérdés nézési terve, vagy `None`, ha nem kell kép (spec §3.1).

    Prioritás: nincs látás-jel → `None`; hálózati kérdés → `None` (minden ágra); körbenézés
    → három állomás; irány + látás-jel → egy címkézett állomás; sima látás-kérdés → egy
    állomás az aktuális pózból. A kérdést EGYSZER tokenizáljuk, és a hálózati próba (nyers
    szavakkal) csak valódi látás-jelnél indul (PR #136 review 9).
    """
    tokens = set(tokenize(question))
    look_around = any(s <= tokens for s in _LOOK_AROUND_TOKEN_SETS)
    if not look_around and not any(s <= tokens for s in _VISION_TOKEN_SETS):
        return None
    if _is_network_question(question, tokens):
        return None
    if look_around:
        return (Station("Előre", 0.0, 0.0), Station("Balra", side_deg, 0.0),
                Station("Jobbra", -side_deg, 0.0))
    poses = {"up": Station("Fent", 0.0, up_deg), "down": Station("Lent", 0.0, -down_deg),
             "left": Station("Balra", side_deg, 0.0), "right": Station("Jobbra", -side_deg, 0.0),
             "forward": Station("Előre", 0.0, 0.0)}
    direction = _direction(question)
    if direction is not None:
        return (poses[direction],)
    return (Station(None, None, None),)


def kell_e_kep(kerdes: str) -> bool:
    """Igaz, ha a kérdés a kamerakép nélkül nem válaszolható meg becsületesen."""
    return vision_plan(kerdes) is not None
