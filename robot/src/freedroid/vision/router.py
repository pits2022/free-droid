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

from freedroid.rag.normalize import tokenize

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
# Teremtő: „a router ezt szűrje ki"). Előtag-illesztés a `wifi`-re, mert a rövid ragozott
# alakok (`wifit`, `wifire`) nem tövezhetők (MIN_STEM). A `Wi-Fi` két tokenre esik
# (`wi`, `fi`) — PÁRBAN kell, mert egy magányos `wi` bármilyen rövid STT-maradék lehet
# (PR #136 review). A kifejezések a KÖZÖS tokenizálón mennek át, mint a látás-listáé,
# hogy egy tövező-változás a kettőt ne vigye szét.
_NETWORK_TOKENS = frozenset(t for k in ("hálózat", "ssid") for t in tokenize(k))
_WI_FI = frozenset(tokenize("Wi-Fi"))

# EGY elem = EGY kifejezés tokenjei, EGYÜTT kellenek (részhalmaz-illesztés).
_VISION_TOKEN_SETS: tuple[frozenset[str], ...] = tuple(
    frozenset(tokenize(kifejezes)) for kifejezes in _LATAS_KIFEJEZESEK)


def _ellenorzi_uresek_ellen(kifejezesek: tuple[str, ...],
                            tokenek: tuple[frozenset[str] | tuple[str, ...], ...]) -> None:
    """I7 (végső review): a részhalmaz-illesztésben egy ÜRES tokenlistájú kifejezés
    (`set() <= barmi`) MINDEN kérdésre illeszkedne — azaz minden kérdés képet kérne.

    Ma egyik kifejezés sem üres — de a spec saját "kell-e kép" listája TARTALMAZZA a
    "mi ez"-t, ami `tokenize()`-on üresre esik (mindkét szó stopszó), és aki "a spec
    szerint" pótolja a hiányzó tételeket, pont ebbe fut bele. Ez a hívás importkor fut,
    tehát a hiba egy NEVEZETT `ValueError`, nem tizenegy rejtélyesen piros teszt."""
    for kifejezes, tok in zip(kifejezesek, tokenek):
        if not tok:
            raise ValueError(
                f"vision.router: {kifejezes!r} üres tokenlistára tövez — a "
                f"részhalmaz-illesztésben ez MINDEN kérdést látás-kérdésnek jelölné")


_ellenorzi_uresek_ellen(_LATAS_KIFEJEZESEK, _VISION_TOKEN_SETS)
# 🔴 A tiltó oldalon a csapda FORDÍTVA ugyanaz (PR #136 review 3): egy üresre eső
# `_WI_FI` (`frozenset() <= barmi`) MINDEN kérdést hálózatinak jelölne — és a látás
# csendben megszűnne. Egy tokenre eső `Wi-Fi` pedig a párban-illesztést rontaná el.
_ellenorzi_uresek_ellen(("hálózat", "ssid"), (_NETWORK_TOKENS,))
if len(_WI_FI) != 2:
    raise ValueError(f"vision.router: a 'Wi-Fi' {sorted(_WI_FI)!r} tokenre esett — "
                     f"pontosan kettő kell (wi, fi), különben a párban-illesztés elromlik")


def _is_network_question(tokens: set[str]) -> bool:
    """Hálózati „látás" — ilyenkor SOHA nincs kép (a Teremtő, 2026-09-15)."""
    return (not tokens.isdisjoint(_NETWORK_TOKENS) or _WI_FI <= tokens
            or any(t.startswith("wifi") for t in tokens))


def kell_e_kep(kerdes: str) -> bool:
    """Igaz, ha a kérdés a kamerakép nélkül nem válaszolható meg becsületesen."""
    kerdes_tokenek = set(tokenize(kerdes))
    if _is_network_question(kerdes_tokenek):
        return False
    return any(token_set <= kerdes_tokenek for token_set in _VISION_TOKEN_SETS)
