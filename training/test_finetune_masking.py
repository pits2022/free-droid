"""A response-masking őre — a v10 egyetlen szerkezeti változtatásának a tesztje.

Miért kell erre teszt: a v9-ig a loss a TELJES szekvenciára futott, és ezt négy verzión
át senki nem vette észre, mert a hibás állapot némán működött. A javítás értéke ezért nem
maga a maszkolás, hanem az, hogy ha a marker-stringek elcsúsznak a chat-templatehez
képest, a futás ELHASAL, nem pedig visszacsúszik a régi viselkedésbe.

A `verify_masking` szándékosan tiszta függvény (nincs benne Unsloth/GPU), hogy off-Pi és
Colab nélkül is futtatható legyen:  python3 -m pytest test_finetune_masking.py
"""
from __future__ import annotations

import pytest

from finetune import _MAX_TRAINED_SHARE, verify_masking

MASK = -100


def _example(prompt_tokens: int, answer_tokens: int) -> list[int]:
    """Egy helyesen maszkolt minta: a prompt -100, a válasz valódi token-id."""
    return [MASK] * prompt_tokens + list(range(1, answer_tokens + 1))


def test_helyes_maszkolas_atmegy():
    # A mért arányok: 4.1% (kanonikus prompt) és 6.1% (rövid 3B prompt).
    batches = [_example(600, 26), _example(400, 26)]
    share = verify_masking(batches)
    assert 0 < share < _MAX_TRAINED_SHARE


def test_minden_maszkolva_elhasal():
    """Ha a VÁLASZ-marker nem illeszkedik, nem marad tanulható token."""
    with pytest.raises(RuntimeError, match="MINDEN token maszkolva"):
        verify_masking([[MASK] * 600, [MASK] * 400])


def test_maszkolas_elmaradasa_elhasal():
    """A veszélyes eset: a maszkolás némán no-op, minden tokenre van loss.

    Ez a v9-ig tartó állapot — a tesztnek pont ezt kell elkapnia.
    """
    with pytest.raises(RuntimeError, match="NEM történt maszkolás"):
        verify_masking([list(range(1, 627)), list(range(1, 427))])


def test_reszleges_maszkolas_is_elhasal_ha_tul_sok_marad():
    """Határeset: ha a marker csak részben illeszkedik, a küszöb fölött el kell hasalnia."""
    with pytest.raises(RuntimeError, match="NEM történt maszkolás"):
        verify_masking([_example(100, 900)])


def test_a_kuszob_alatt_atmegy():
    """A küszöb alatt viszont nem hasal el — nem akarunk fals riasztást rövid promptnál."""
    assert verify_masking([_example(700, 300)]) == pytest.approx(0.3)


def test_tomb_alaku_labels_ugyanazt_adja():
    """Tömb-alakú `labels` (torch/numpy) esetén ugyanaz jöjjön ki, mint listával.

    A `datasets.Dataset` ma listát ad, de torch-formátumú dataseten tenzor jönne. A
    veszély nem a lassulás (mérve: 0.08 ms), hanem hogy egy némán FÉLRESZÁMOLÓ guard
    pont azt a hibát engedné át, ami ellen véd.
    """
    np = pytest.importorskip("numpy")
    listaval = verify_masking([_example(600, 26), _example(400, 26)])
    tombbel = verify_masking([np.array(_example(600, 26)), np.array(_example(400, 26))])
    assert tombbel == pytest.approx(listaval)

    # És a hibás esetet is ugyanúgy el kell kapnia tömbön.
    with pytest.raises(RuntimeError, match="NEM történt maszkolás"):
        verify_masking([np.arange(1, 627)])
