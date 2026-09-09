"""Egyetlen képkocka a webkamerából — a látás-ág bemenete.

A `cap_factory` befecskendezés a `FallbackLLMClient(client_factory=...)` és a
`CloudWhisperSTT(opener=...)` mintája: a hardver-seam kicserélhető, a mért logika
(eszköz-próba, bemelegítés, JPEG-kódolás) a VALÓDI kód. A hamis kamera VALÓDI numpy
tömböt ad, tehát a kódolást az igazi cv2 végzi — az sem feltételezés.
"""

from __future__ import annotations

import numpy as np

from freedroid.camera.frame import BEMELEGITO_KOCKAK, elso_kepkocka, grab_jpeg


class HamisKamera:
    """Egy `cv2.VideoCapture`-szerű objektum. `kepek=0` -> megnyílik, de nem ad képet."""

    def __init__(self, eszkoz: str, nyithato: bool = True, kepek: int = 99) -> None:
        self.eszkoz = eszkoz
        self._nyithato = nyithato
        self._kepek = kepek
        self.olvasasok = 0
        self.elengedve = False

    def isOpened(self) -> bool:  # noqa: N802 — a cv2 API neve
        return self._nyithato

    def read(self):
        self.olvasasok += 1
        if self.olvasasok > self._kepek:
            return False, None
        return True, np.full((4, 4, 3), 128, dtype=np.uint8)

    def release(self) -> None:
        self.elengedve = True


def gyar(**eszkozok):
    """`{"/dev/video0": HamisKamera(...)}` -> a `cap_factory`. A nem felsorolt eszköz
    meg sem nyílik."""
    keszult: list[HamisKamera] = []

    def factory(eszkoz: str):
        k = eszkozok.get(eszkoz) or HamisKamera(eszkoz, nyithato=False)
        keszult.append(k)
        return k

    return factory, keszult


def test_a_kepet_NEM_ado_eszkozt_atugorja():
    """🔴 A Pi 5-ön 20+ /dev/video* van, a felük ISP/kodek csomópont: MEGNYÍLIK, de nem
    ad képet. A jelenlét nem bizonyíték, a képkocka az."""
    factory, _ = gyar(**{"/dev/video0": HamisKamera("/dev/video0", kepek=0),
                         "/dev/video1": HamisKamera("/dev/video1")})
    hol, kocka = elso_kepkocka(cap_factory=factory)
    assert hol == "/dev/video1"
    assert kocka is not None


def test_bemelegito_kockakat_olvas():
    """Az első kockák feketék, amíg az automatika beáll — egy rögtön kiolvasott kocka
    EGYENLETES lenne, azaz a mérőeszköz gyártaná pont azt a hibát, amit keres."""
    kamera = HamisKamera("/dev/video0")
    factory, _ = gyar(**{"/dev/video0": kamera})
    elso_kepkocka(cap_factory=factory)
    assert kamera.olvasasok == BEMELEGITO_KOCKAK


def test_mindig_elengedi_az_eszkozt():
    """Egy nyitva felejtett kamera a KÖVETKEZŐ kört buktatná meg (foglalt eszköz)."""
    kamera = HamisKamera("/dev/video0", kepek=0)
    factory, keszult = gyar(**{"/dev/video0": kamera})
    elso_kepkocka(cap_factory=factory)
    assert all(k.elengedve for k in keszult if k.isOpened())


def test_ha_egyik_eszkoz_sem_ad_kepet_akkor_None_nem_kivetel():
    """A látás hiánya NEM hiba: az orchestrátor ebből a negatív blokkot építi."""
    factory, _ = gyar()
    assert elso_kepkocka(cap_factory=factory) == (None, None)
    assert grab_jpeg(cap_factory=factory) is None


def test_a_grab_jpeg_VALODI_jpeg_bajtokat_ad():
    factory, _ = gyar(**{"/dev/video0": HamisKamera("/dev/video0")})
    adat = grab_jpeg(cap_factory=factory)
    assert adat is not None
    assert adat[:2] == b"\xff\xd8", "nem JPEG-fejléc"      # SOI marker
    assert adat[-2:] == b"\xff\xd9", "csonka JPEG"          # EOI marker
