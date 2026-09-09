"""A látás-router: melyik kérdés kap képkockát.

Determinisztikus, nem osztályozó. A mért RAG-tanulság áll rá: ALKOTÁS-KÉRÉS és PARANCS
ne kapjon kontextust — a „Szabi, gyere ide!" nem indíthat képfeltöltést. (A hosszpadló-
mérésben épp egy 3 szavas parancsra kirakott mondat-padló vitte el a <tool> blokkot és
szült képesség-hallucinációt.)
"""

from __future__ import annotations

import pytest

from freedroid.vision.router import kell_e_kep

LATAS = [
    "Mit látsz?",
    "Mit látsz most a kamerádon?",
    "Látod, hány ember van itt?",
    "Nézz körül és mondd el, mi van körülötted!",
    "Kit látsz magad előtt?",
    "Milyen színű a pólóm?",
]

NEM_LATAS = [
    "Szabi, gyere ide!",                       # PARANCS — a mért ellenpélda
    "Fordulj balra kilencven fokot!",          # PARANCS
    "Írj egy haikut a teremtődről!",           # ALKOTÁS-KÉRÉS — a mért ellenpélda
    "Mit jelent a neved?",                     # persona
    "Mesélj a Yotengritről!",                  # RAG-kérdés
    "Hogy vagy ma?",                           # köszönés/small talk
    "Állj meg!",                               # PARANCS
]


@pytest.mark.parametrize("kerdes", LATAS)
def test_a_latas_kerdesek_kepet_kernek(kerdes):
    assert kell_e_kep(kerdes) is True, kerdes


@pytest.mark.parametrize("kerdes", NEM_LATAS)
def test_a_parancsok_es_alkotas_keresek_NEM(kerdes):
    """🔴 Ez a teszt fogja meg a túl széles kulcsszó-listát. Ha egy hétköznapi tő
    (pl. „van", „ez") bekerül a halmazba, MINDEN kérdés képet kérne — és a robot
    körönként 2-3 másodpercet veszítene a semmiért."""
    assert kell_e_kep(kerdes) is False, kerdes


def test_az_ures_kerdes_nem_ker_kepet():
    assert kell_e_kep("") is False
    assert kell_e_kep("   ") is False


def test_a_kulcsszavak_es_a_kerdes_UGYANAZON_a_tokenizalon_megy_at():
    """A ragozott alakoknak működniük kell anélkül, hogy kézzel tövezett listát
    írnánk — ez az egész felépítés indoka."""
    assert kell_e_kep("látsz valamit?") is True
    assert kell_e_kep("Látod ezt?") is True
    assert kell_e_kep("Mit fogsz látni?") is True
