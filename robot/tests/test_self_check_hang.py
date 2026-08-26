"""A hurok-teszt SZÁMTANI fele, hardver nélkül.

Miért ér ez tesztet, amikor a mérés hangkártyán fut: a roboton mért arány 8700-12600
volt, a küszöb 50 — ekkora tartalék mellett a hardveres futás akkor is zöld, ha az
elemzés hibás (rossz ablak, elcsúszott frekvencia-tengely, DC-csúcs). Vagyis pont a
jelenség, amit mérünk, TAKARJA EL a mérőeszköz hibáját. Szintetikus jellel viszont
azonnal kiderül.
"""

from __future__ import annotations

import math
import random

from self_check import TONE_HZ, TONE_MIN_ARANY, _hangminta, hang_elemzes

RATE = 16000


def test_tiszta_hang_a_kiadott_frekvencian_jelenik_meg():
    hz, arany, rms = hang_elemzes(_hangminta(RATE, TONE_HZ, 1.0), RATE)
    assert abs(hz - TONE_HZ) < 50
    assert arany > TONE_MIN_ARANY
    assert rms > 20


def test_zajra_nincs_csucs():
    """A NEGATÍV eset: néma hangszóró mellett a mikrofon zajt vesz fel. Az aránynak a
    küszöb alá kell esnie — enélkül a check bármire zöldet mondana."""
    rnd = random.Random(7)
    zaj = bytes()
    minta = [int(rnd.gauss(0, 300)) for _ in range(RATE)]
    for v in minta:
        zaj += max(-32768, min(32767, v)).to_bytes(2, "little", signed=True)
    _hz, arany, _rms = hang_elemzes(zaj, RATE)
    assert arany < TONE_MIN_ARANY


def test_a_masik_frekvenciat_is_megtalalja():
    """Nem beégetett 1 kHz: a mérőnek a TÉNYLEGES csúcsot kell megtalálnia, különben
    a "csúcs a kiadott hangon van" állítás tautológia lenne."""
    hz, _arany, _rms = hang_elemzes(_hangminta(RATE, 2500.0, 1.0), RATE)
    assert abs(hz - 2500.0) < 50


def test_a_dc_eltolas_nem_lesz_csucs():
    """Egy egyenáramú eltolás (hangkártyák viszik) a spektrum [0] vödrét emeli meg.
    Ha az elemzés azt is beszámítaná, egy NÉMA felvétel is hatalmas arányt adna —
    tehát a néma mikrofon nézne ki működő huroknak. Az első változat PONTOSAN ezt tette
    (a [0] vödör kihagyása kevés: az ablakozás szétkeni a szomszédokba), ez a teszt
    fogta meg."""
    n = RATE
    dc = b"".join((8000).to_bytes(2, "little", signed=True) for _ in range(n))
    _hz, arany, rms = hang_elemzes(dc, RATE)
    assert arany < TONE_MIN_ARANY
    # És az RMS is a "néma mikrofon" ágra visz, nem a "néma hangszóró"-ra.
    assert rms < 20


def test_hangminta_hossza_es_amplitudoja():
    pcm = _hangminta(RATE, TONE_HZ, 0.5, amp=0.5)
    assert len(pcm) == int(RATE * 0.5) * 2
    _hz, _arany, rms = hang_elemzes(pcm, RATE, eldob_s=0.0)
    # Szinusz effektív értéke = amplitúdó / gyök(2).
    assert math.isclose(rms, 0.5 * 32767 / math.sqrt(2), rel_tol=0.02)
