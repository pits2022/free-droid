"""A látás-router: melyik kérdés kap képkockát.

Determinisztikus, nem osztályozó. A mért RAG-tanulság áll rá: ALKOTÁS-KÉRÉS és PARANCS
ne kapjon kontextust — a „Szabi, gyere ide!" nem indíthat képfeltöltést. (A hosszpadló-
mérésben épp egy 3 szavas parancsra kirakott mondat-padló vitte el a <tool> blokkot és
szült képesség-hallucinációt.)
"""

from __future__ import annotations

import pytest

from freedroid.vision.router import Station, _ellenorzi_uresek_ellen, kell_e_kep, vision_plan

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
    "Hányan vannak a teremben?",               # PR #129 review — páros kifejezés
    # 🔴 Az STT így hallotta a „Mit látsz?"-t (élő menet, 2026-09-15, transcript
    # szó szerint): router nélkül ezek a körök [LÁTVÁNY] nélkül mentek, és a modell
    # kitalálta, mit lát („Egy sötét távoli helyiséget látok").
    "Mitlát!",
    "Mit látze?",
    "Mit látza?",
    "Mondel mit Lats.",
    "Meet lads!",
    "Mit, lads?",
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
    "Hányan laknak Magyarországon?",           # PR #129 review — a csupasz "hányan" hamis pozitívja
    "Hányan képviselik a törzset?",            # PR #129 review — ua.
    # 🔴 Hálózati „látás" (élő menet, 2026-09-15): a `látsz` tüzelt, és a robot a wifik
    # helyett a szobát írta le — a Teremtő: „a router ezt szűrje ki".
    "Mit látsz a hálózaton?",
    "Sorold fel, hogy milyen hálózatokat látsz a Wi-Fi-n.",
    "Milyen wifit látsz?",
    "Látod a wifire kapcsolódó eszközöket?",
    "Mit látsz a Wi-Fi-n?",                    # PR #136 review — Wi-Fi a „hálózat" szó NÉLKÜL
    "Milyen SSID-ket látsz?",                  # PR #136 review — az ssid ág külön is
    # PR #136 review 6 — kötőjel nélkül ragozva a rövid alak nem tövez (MIN_STEM):
    "Milyen ssidet látsz?",
    "Milyen ssidt látsz?",
    "Milyen wlant látsz?",
    "Mit látsz a WLAN-on?",
    # PR #136 review 8 — kötőjellel ragozva a `Wi-Fi` tokenje `wi` + `fit`:
    "Látsz Wi-Fit?",
    "Mit látsz a Wi-Fire?",
    "Látsz Wi\u2013Fit?",                       # PR #137 review 6 — gondolatjellel
    # PR #136 review 10 — a képzett „hálózati" alakot a tövező nem vágja vissza:
    "Milyen hálózati eszközöket látsz?",
    "Mit látsz a hálózati eszközökön?",
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


@pytest.mark.parametrize("question", ["Wi, mit látsz?", "Fi, mit látsz?"])
def test_lone_wi_or_fi_token_does_not_block_vision(question):
    """A `wi` és a `fi` csak PÁRBAN hálózati jel (PR #136 review): egy rövid STT-maradék
    ne némítsa el a látást."""
    assert kell_e_kep(question) is True


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


def test_empty_guard_rejects_length_mismatch():
    """PR #136 review 3: két kifejezés, egy halmaz — a sima `zip` a második kifejezést
    sosem nézte volna meg. Hosszeltérésnél importkor, hangosan bukjon."""
    with pytest.raises(ValueError, match=r"shorter|longer"):
        _ellenorzi_uresek_ellen(("hálózat", "ssid"), (frozenset({"halozat"}),))


def test_empty_guard_names_its_context():
    """PR #136 review 5: a hálózati listán egy üres kifejezés a látást némítaná el, nem
    mindent képnek jelölne — a hibaüzenet mondja meg, melyik listáról van szó."""
    with pytest.raises(ValueError, match=r"\(hálózat\)"):
        _ellenorzi_uresek_ellen(("mi ez",), ((),), "hálózat")


def test_az_ures_tokenlistaju_kifejezes_HANGOSAN_bukik():
    """I7 (végső review): a spec saját "kell-e kép" listája tartalmazza a "mi ez"-t,
    ami `tokenize()`-on ÜRES listát ad (mindkét szó stopszó) — a részhalmaz-illesztésben
    ez MINDEN kérdésre illeszkedne (`set() <= barmi`). A guard importkor fusson, tehát a
    hiba egy NEVEZETT `ValueError`, nem tizenegy rejtélyesen piros teszt."""
    with pytest.raises(ValueError, match="mi ez"):
        _ellenorzi_uresek_ellen(("mi ez",), ((),))


LOOK_AROUND = (Station("Előre", 0.0, 0.0), Station("Balra", 45.0, 0.0),
               Station("Jobbra", -45.0, 0.0))


@pytest.mark.parametrize("question", [
    "Nézz körül és mondd el, mit látsz.",
    "Nézz körül a kameráddal!",
    "Nézz szét a szobában!",
    "Nézzél körül!",
    "Pásztázz körbe a kameráddal!",
    "Nézz körbe!",
    "Nézzél körbe!",                     # PR #137 review 5
    "Pásztázd körbe a szobát!",
])
def test_look_around_is_three_stations(question):
    assert vision_plan(question) == LOOK_AROUND


@pytest.mark.parametrize("question, station", [
    ("Nézz fel és mondd el, mit látsz.", Station("Fent", 0.0, 30.0)),
    ("Nézz felfelé, mit látsz?", Station("Fent", 0.0, 30.0)),
    ("Nézz a plafonra, mit látsz?", Station("Fent", 0.0, 30.0)),
    ("Nézz le és mondd el, mit látsz.", Station("Lent", 0.0, -30.0)),
    ("Nézz a földre, és mondd el, mit látsz előtted.", Station("Lent", 0.0, -30.0)),
    ("Nézz lefelé és mond el, mit látsz.", Station("Lent", 0.0, -30.0)),
    ("Nézz balra, mit látsz?", Station("Balra", 45.0, 0.0)),
    ("Nézz jobbra és mondd el, mit látsz!", Station("Jobbra", -45.0, 0.0)),
])
def test_direction_with_vision_cue_is_one_labelled_station(question, station):
    assert vision_plan(question) == (station,)


def test_bare_look_up_is_NOT_a_vision_question():
    """A csupasz „Nézz fel!" kamera-parancs a modelltől, nem látás-kör (spec §3.1)."""
    assert vision_plan("Nézz fel!") is None
    assert vision_plan("Nézz balra!") is None


def test_direction_word_must_follow_the_verb():
    """„Nézz rám és írd le, mit látsz" — a `le` az „írd le" része, nem irány."""
    assert vision_plan("Nézz rám és írd le, mit látsz!") == (Station(None, None, None),)


def test_plain_vision_question_keeps_the_current_pose():
    assert vision_plan("Mit látsz?") == (Station(None, None, None),)


def test_angles_come_from_the_caller():
    plan = vision_plan("Nézz körül!", side_deg=30.0)
    assert [s.pan_deg for s in plan] == [0.0, 30.0, -30.0]
    assert vision_plan("Nézz fel, mit látsz?", up_deg=20.0) == (Station("Fent", 0.0, 20.0),)


def test_network_block_applies_to_every_branch():
    assert vision_plan("Nézz körül a wifin!") is None
    assert vision_plan("Nézz fel és mondd, milyen hálózatot látsz!") is None


@pytest.mark.parametrize("question", LATAS + NEM_LATAS)
def test_kell_e_kep_is_a_thin_wrapper(question):
    assert kell_e_kep(question) == (vision_plan(question) is not None)


@pytest.mark.parametrize("question, station", [
    ("Nézz kérlek a földre, mit látsz?", Station("Lent", 0.0, -30.0)),   # PR #137 review: 2 töltelékszó
    ("Nézz egy kicsit balra, mit látsz?", Station("Balra", 45.0, 0.0)),
    ("Nézz a padlóra, mit látsz?", Station("Lent", 0.0, -30.0)),
])
def test_direction_window_and_padlora(question, station):
    assert vision_plan(question) == (station,)


def test_half_specified_station_fails_loudly():
    """PR #137 review: a végrehajtó a `pan_deg`-ből dönti el a pózt — egy félig megadott
    állomás ne hagyja ki csendben a tiltet."""
    with pytest.raises(ValueError, match="együtt"):
        Station("Fent", None, 30.0)
    assert Station() == Station(None, None, None)


@pytest.mark.parametrize("question, station", [
    ("Nézz előre, mit látsz?", Station("Előre", 0.0, 0.0)),        # PR #137 review: a fej visszajön
    ("Nézz szembe és mondd el, mit látsz!", Station("Előre", 0.0, 0.0)),
    ("Balra nézz, mit látsz?", Station("Balra", 45.0, 0.0)),        # PR #137 review: fókuszpozíció
    ("A földre nézz, mit látsz?", Station("Lent", 0.0, -30.0)),
])
def test_forward_and_direction_before_the_verb(question, station):
    assert vision_plan(question) == (station,)


def test_only_one_word_before_the_verb_counts():
    """„Írd le és nézz rám, mit látsz" — a `le` két szóval az ige előtt van, nem irány."""
    assert vision_plan("Írd le és nézz rám, mit látsz!") == (Station(None, None, None),)


@pytest.mark.parametrize("question", [
    "Nézz oda, írd le, mit látsz!",          # PR #137 review 4: az „írd le" igekötője
    "Nézz rám, aztán mondd fel, mit látsz!",
])
def test_preverb_of_another_verb_is_not_a_direction(question):
    assert vision_plan(question) == (Station(None, None, None),)


@pytest.mark.parametrize("question, station", [
    ("Nézz le, mit látsz?", Station("Lent", 0.0, -30.0)),
    ("Le nézz, mit látsz?", Station("Lent", 0.0, -30.0)),
    ("Nézz kérlek a földre, mit látsz?", Station("Lent", 0.0, -30.0)),
])
def test_preverb_adjacent_and_unambiguous_word_in_window_still_work(question, station):
    assert vision_plan(question) == (station,)


@pytest.mark.parametrize("question, station", [
    ("Nézz egy kicsit balrafelé, mit látsz?", Station("Balra", 45.0, 0.0)),   # PR #137 review 5
    ("Nézz jobbrafelé, mit látsz?", Station("Jobbra", -45.0, 0.0)),
])
def test_felé_forms_of_left_and_right(question, station):
    assert vision_plan(question) == (station,)
