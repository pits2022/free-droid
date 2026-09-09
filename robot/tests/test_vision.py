"""A felhős VLM kliense.

A modul tétele NEM az, hogy „HTTP-t hív", hanem hogy a látás bukása SOSEM viszi el a
kört: minden hibaág `None`-t ad, indokkal a naplóban. Az orchestrátor ebből építi a
negatív [LÁTVÁNY] blokkot (spec §4.5).
"""

from __future__ import annotations

import base64
import dataclasses

import pytest

from freedroid.config.settings import Settings, VisionSettings
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
    """A `http_get` a `vision` modul NÉVTERÉBEN cserélendő (ott importáltuk), a
    `uj_kor()` pedig azért kell, mert a kör-hatókörű elérhetetlen-cache MODUL-szintű:
    egy előző teszt által halottnak jelölt host átszivárogna ebbe a tesztbe."""
    from freedroid.health import probe

    probe.uj_kor()
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
