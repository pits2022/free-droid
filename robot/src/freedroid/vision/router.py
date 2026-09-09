"""Kell-e képkocka ehhez a kérdéshez.

Determinisztikus kulcsszó-illesztés, NEM osztályozó és NEM tool. A döntés az
orchestrátoré (spec §3/3. döntés): a mért tool-gyengeség (kitalált `action` értékek,
hiányzó irány) így nem tud elrontani semmit, és a `KNOWN_TOOLS` változatlan marad.

🔴 A MÉRT SZABÁLY, amit követ: ALKOTÁS-KÉRÉS ÉS PARANCS NE KAPJON KONTEXTUST. A
RAG-nál ez mérésből jött (a „Szabi, gyere ide!" mindhárom mintájában elveszett a
<tool> blokk, és a modell képességet hallucinált, amint hosszpadlót kapott). Ugyanez
áll a látásra: egy parancsra elküldött képkocka 2-3 másodpercet visz el a semmiért.

A kulcsszavak ÉS a kérdés UGYANAZON a tokenizálón mennek át — így a ragozás
(„látsz"/„látod"/„látni") magától működik, és nem kell kézzel tövezett listát
karbantartani.
"""

from __future__ import annotations

from freedroid.rag.normalize import tokenize

# SZŰK lista, szándékosan. Bővíteni csak úgy szabad, hogy a
# `test_a_parancsok_es_alkotas_keresek_NEM` teszt zöld marad: egy hétköznapi tő
# („van", „ez") bekerülése MINDEN kérdést látás-kérdéssé tenne.
_LATAS_KIFEJEZESEK = (
    "látsz",
    "látod",
    "látni",
    "nézz körül",
    "kit látsz",
    "milyen színű",
)

_LATAS_TOKENEK = frozenset(
    t for kifejezes in _LATAS_KIFEJEZESEK for t in tokenize(kifejezes))


def kell_e_kep(kerdes: str) -> bool:
    """Igaz, ha a kérdés a kamerakép nélkül nem válaszolható meg becsületesen."""
    return bool(_LATAS_TOKENEK & set(tokenize(kerdes)))
