"""A felhős VLM kliense.

A modul tétele NEM az, hogy „HTTP-t hív", hanem hogy a látás bukása SOSEM viszi el a
kört: minden hibaág `None`-t ad, indokkal a naplóban. Az orchestrátor ebből építi a
negatív [LÁTVÁNY] blokkot (spec §4.5).
"""

from __future__ import annotations

import base64
import dataclasses
import logging

import pytest

from freedroid.config.settings import Settings, VisionSettings
from freedroid.health.probe import korben_elerhetetlen
from freedroid.vision import CloudVLM

URL = "http://10.0.0.1:11434"
JPEG = b"\xff\xd8hamis-kep\xff\xd9"


class HamisOllama:
    def __init__(self, host: str, timeout: float, valasz="A room with a table.",
                 hiba: Exception | None = None) -> None:
        self.host, self.timeout = host, timeout
        self._valasz, self._hiba = valasz, hiba
        self.hivasok: list[dict] = []

    def generate(self, **kw):
        self.hivasok.append(kw)
        if self._hiba is not None:
            raise self._hiba
        return {"response": self._valasz}


class Halo:
    def __init__(self, elerheto: bool = True, **kw) -> None:
        self.elerheto, self.kw = elerheto, kw
        self.peldanyok: list[HamisOllama] = []

    def http_get(self, url: str, timeout: float = 4.0):
        return (200 if self.elerheto else 0), ""

    def gyar(self, host: str, timeout: float):
        p = HamisOllama(host, timeout, **self.kw)
        self.peldanyok.append(p)
        return p


def beallitas(**kw) -> Settings:
    alap = {"enabled": True, "model": "hamis-vlm:latest"}
    return dataclasses.replace(Settings(), vision=VisionSettings(**(alap | kw)))


def kliens(monkeypatch, halo: Halo, **kw) -> CloudVLM:
    """A `http_get` a `vision` modul NÉVTERÉBEN cserélendő (ott importáltuk). A
    kör-hatókörű elérhetetlen-cache friss állapotát a `conftest.py` autouse
    `_friss_kor` fixture-je adja minden teszt köré — nincs itt külön `uj_kor()`."""
    monkeypatch.setattr("freedroid.vision.http_get", halo.http_get)
    return CloudVLM(settings=beallitas(**kw), client_factory=halo.gyar)


def test_a_kep_base64_kodolva_megy_fel():
    """Az Ollama `images` mezője base64 sztringeket vár, nem nyers bájtokat."""
    halo = Halo()
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    v.describe(JPEG)
    (hivas,) = halo.peldanyok[0].hivasok
    assert hivas["images"] == [base64.b64encode(JPEG).decode("ascii")]
    assert hivas["model"] == "hamis-vlm:latest"
    assert hivas["stream"] is False


def test_a_hivas_NEM_gondolkodik_es_bent_tartja_a_modellt():
    """🔴 `think=False` nélkül a qwen3.5 egy mondatért 6-10 s-ot gondolkodik (WP0) — a
    8 s-os korlát mellett rendszeres negatív blokk. A `keep_alive` SZÁMKÉNT/durationként
    megy (a `"-1"` sztring 400-at ad), és a valódi híváson is, nem csak a bemelegítésen."""
    halo = Halo()
    v = CloudVLM(settings=beallitas(keep_alive="-1"), client_factory=halo.gyar)
    v.describe(JPEG)
    (hivas,) = halo.peldanyok[0].hivasok
    assert hivas["think"] is False
    assert hivas["keep_alive"] == -1


def test_a_bemelegites_HOSSZU_korlattal_kep_nelkul_tolt(monkeypatch):
    """A lemezről betöltés 29,75 s — a 8 s-os `timeout_s`-sel a bemelegítés maga is
    időtúllépne. Üres prompt, kép nélkül: az Ollama erre csak betölt."""
    halo = Halo()
    v = kliens(monkeypatch, halo, timeout_s=8.0, warmup_timeout_s=60.0)
    assert v.warmup() is True
    (p,) = halo.peldanyok
    assert p.timeout == 60.0
    (hivas,) = p.hivasok
    assert hivas == {"model": "hamis-vlm:latest", "prompt": "", "stream": False,
                     "keep_alive": "30m", "options": {"num_ctx": 2048}}


def test_a_bemelegites_es_a_hivas_UGYANAZZAL_a_kontextussal_megy(monkeypatch):
    """🔴 Eltérő `num_ctx`-re az Ollama újratölti a modellt (mérve 3,92 s) — a
    bemelegítés akkor semmit sem érne. A 262K-s alap 12 GB VRAM, a 2048 3,1 GB."""
    halo = Halo()
    v = kliens(monkeypatch, halo, num_ctx=4096)
    v.warmup()
    v.describe(JPEG)
    meleg, hivas = (p.hivasok[0] for p in halo.peldanyok)
    assert meleg["options"] == hivas["options"] == {"num_ctx": 4096}


def test_a_bemelegites_SOSEM_dob_es_kikapcsolva_meg_sem_hiv(monkeypatch):
    halo = Halo(hiba=ConnectionError("boom"))
    assert kliens(monkeypatch, halo).warmup() is False
    ki = Halo()
    assert kliens(monkeypatch, ki, enabled=False).warmup() is False
    assert ki.peldanyok == []
    halott = Halo(elerheto=False)
    assert kliens(monkeypatch, halott).warmup() is False
    assert halott.peldanyok == []


def test_a_hibas_keep_alive_INDULASKOR_bukik():
    with pytest.raises(ValueError, match="vision.keep_alive"):
        VisionSettings(keep_alive="soha")


def test_a_leiras_visszajon_tisztitva():
    halo = Halo(valasz="  A room with a table.\n")
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(JPEG) == "A room with a table."


def test_a_hiba_NEM_dob_hanem_None():
    """🔴 A látás bukása nem viheti el a kört. Az STT-vel ELLENTÉTBEN (ott a hiba azt
    jelenti, hogy nincs is kérdés) itt a hiba egy túlélhető állapot, amit a robot ki
    tud mondani."""
    halo = Halo(hiba=TimeoutError("boom"))
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(JPEG) is None


def test_a_kikapcsolt_latas_meg_sem_hiv():
    halo = Halo()
    v = CloudVLM(settings=beallitas(enabled=False), client_factory=halo.gyar)
    assert v.describe(JPEG) is None
    assert halo.peldanyok == []


def test_az_ures_kep_meg_sem_hiv():
    halo = Halo()
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(b"") is None
    assert halo.peldanyok == []


def test_a_rossz_valasz_alak_SEM_dob():
    """A modul EGY szabálya: `describe()` SOSEM dob. A válasz-kinyerés (`.get`/
    `getattr`/`.strip()`) az őrzött ágon KÍVÜL futott — egy nem-sztring `response`
    mező itt dobott volna, és épp azt a kört vitte volna el, amit a modul védeni
    hivatott."""
    halo = Halo(valasz=123)  # a `response` mező NEM sztring
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(JPEG) is None


def test_a_response_nelkuli_objektum_SEM_dob():
    class UresValasz:
        """Se `.get`, se `response` attribútum."""

    def gyar(host, timeout):
        class Kliens:
            def generate(self, **kw):
                return UresValasz()

        return Kliens()

    v = CloudVLM(settings=beallitas(), client_factory=gyar)
    assert v.describe(JPEG) is None


def test_az_elerhetetlen_felho_INDOKKAL_ter_vissza(monkeypatch):
    """Az indok azért kell, mert a naplóban a „miért nem látott?" kérdés csak így
    válaszolható meg utólag — ugyanaz az elv, mint a FallbackLLMClient._probe-nál."""
    halo = Halo(elerheto=False)
    v = kliens(monkeypatch, halo)
    rendben, indok = v.elerheto()
    assert rendben is False
    assert URL in indok


def test_az_enabled_ures_modellel_INDULASKOR_bukik():
    """Egy bekapcsolt, de modell nélküli látás CSENDBEN sosem látna semmit."""
    with pytest.raises(ValueError, match="vision_model|model"):
        VisionSettings(enabled=True, model="")


def test_a_kapcsolodasi_hiba_a_hostot_ELERHETETLENNEK_jeloli():
    """I1 (végső review): eddig a `describe()` MEGTUDTA a kapcsolódási hibából, hogy a
    host halott, de nem szólt a `korben_elerhetetlen` cache-nek — a kör hátralévő
    részében (STT/LLM próba ugyanarra a hostra) ez feleslegesen kivárt volna még egy
    időkorlátot."""
    halo = Halo(hiba=ConnectionError("boom"))
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(JPEG) is None
    assert korben_elerhetetlen(URL) is True


def test_a_valaszalak_hibaja_NEM_jeloli_elerhetetlennek():
    """Ellenpróba: egy rossz VÁLASZALAK (a host FELELT, csak érvénytelenül) nem
    kapcsolódási hiba, tehát NEM jelölheti halottnak a hostot — az `AttributeError`
    a `.strip()`-en nem `OSError`."""
    halo = Halo(valasz=123)  # a `response` mező NEM sztring -> `.strip()` AttributeError
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)
    assert v.describe(JPEG) is None
    assert korben_elerhetetlen(URL) is False


def test_a_latvany_SZOVEGE_csak_DEBUG_szinten_megy(caplog):
    """I2 (végső review): a leírás SZÖVEGE (akár egy hallgató arcáról) korábban INFO
    szinten ment a journald-ba — az PERZISZTENS, és a demó előtti törlés
    (`find /var/log/freedroid -delete`) nem éri el. A hossz maradhat INFO-n
    (demó-posztúra jelzés), a szöveg csak DEBUG-on látszódjon."""
    halo = Halo(valasz="Egy konkrét arc leírása.")
    v = CloudVLM(settings=beallitas(), client_factory=halo.gyar)

    caplog.set_level(logging.INFO, logger="freedroid.vision")
    v.describe(JPEG)
    info_uzenetek = " ".join(r.getMessage() for r in caplog.records)
    assert "Egy konkrét arc leírása" not in info_uzenetek

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger="freedroid.vision")
    v.describe(JPEG)
    debug_uzenetek = " ".join(r.getMessage() for r in caplog.records)
    assert "Egy konkrét arc leírása" in debug_uzenetek
