"""A látás-router: melyik kérdés kap képkockát.

Determinisztikus, nem osztályozó. A mért RAG-tanulság áll rá: ALKOTÁS-KÉRÉS és PARANCS
ne kapjon kontextust — a „Szabi, gyere ide!" nem indíthat képfeltöltést. (A hosszpadló-
mérésben épp egy 3 szavas parancsra kirakott mondat-padló vitte el a <tool> blokkot és
szült képesség-hallucinációt.)
"""

from __future__ import annotations

import pytest

from freedroid.vision.router import _ellenorzi_uresek_ellen, kell_e_kep

LATAS = [
    "Mit látsz?",
    "Mit látsz most a kamerádon?",
    "Látod, hány ember van itt?",
    "Nézz körül és mondd el, mi van körülötted!",
    "Kit látsz magad előtt?",
    "Milyen színű a pólóm?",
    "Mit lát a kamerád?",                      # javítás — MIN_STEM=6 miatt nem tövezhető
    "Mit láttál eddig?",                       # javítás — ua.
    "Hányan vagytok itt?",                     # I5, végső review — a spec listájának tagja
]

NEM_LATAS = [
    "Szabi, gyere ide!",                       # PARANCS — a mért ellenpélda
    "Fordulj balra kilencven fokot!",          # PARANCS
    "Írj egy haikut a teremtődről!",           # ALKOTÁS-KÉRÉS — a mért ellenpélda
    "Mit jelent a neved?",                     # persona
    "Mesélj a Yotengritről!",                  # RAG-kérdés
    "Hogy vagy ma?",                           # köszönés/small talk
    "Állj meg!",                               # PARANCS
    "Menj körbe a szoba körül!",               # javítás — PARANCS, csak "körül" nem elég
    "Kit hívjak, ha baj van?",                 # javítás — "kit" önmagában nem elég
    "Nézz utána, mikor van a következő szünet!",  # javítás — idiomatikus "nézz utána"
    "Kit ismersz még a Teremtőn kívül?",       # javítás — "kit" önmagában nem elég
    "Fordulj az előtted lévő fal felé!",       # I5, végső review — "előtted" NEM került fel
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


def test_a_tobbszavas_kifejezes_MINDEN_tokenje_kell():
    """A mechanizmus önmagában: egy `nézz` + `körül` PÁR kell, nem elég csak az egyik.
    Ha egy jövőbeli refaktor visszaáll lapos halmazra, ez a teszt hangosan bukjon."""
    assert kell_e_kep("Nézz be a szomszédba!") is False
    assert kell_e_kep("Nézz körül a szobában!") is True


def test_az_ures_tokenlistaju_kifejezes_HANGOSAN_bukik():
    """I7 (végső review): a spec saját "kell-e kép" listája tartalmazza a "mi ez"-t,
    ami `tokenize()`-on ÜRES listát ad (mindkét szó stopszó) — a részhalmaz-illesztésben
    ez MINDEN kérdésre illeszkedne (`set() <= barmi`). A guard importkor fusson, tehát a
    hiba egy NEVEZETT `ValueError`, nem tizenegy rejtélyesen piros teszt."""
    with pytest.raises(ValueError, match="mi ez"):
        _ellenorzi_uresek_ellen(("mi ez",), ((),))
