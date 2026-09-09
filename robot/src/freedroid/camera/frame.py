"""Egyetlen képkocka a webkamerából — a látás-ág BEMENETE.

A `camera/__init__.py` a szervókat mozgatja (aktuátor); ez OLVAS. A két felelősség
szándékosan külön fájlban van: a pan/tilt az I2C-buszon dől el, ez a V4L2-n.

🔴 A KÉT MÉRT TULAJDONSÁG, ami miatt ez nem három sor (a `self_check.py`-ból költözött
ide, ahol 2026-08 óta bizonyított):

1. A Pi 5-ön 20+ `/dev/video*` van, és a felük ISP/kodek csomópont: MEGNYÍLIK, de nem
   ad képkockát. A jelenlét tehát nem bizonyíték — a képkocka az.
2. Az első kockák jellemzően feketék, amíg az automatika beáll. Egy rögtön kiolvasott
   kocka EGYENLETES volna, azaz a mérőeszköz gyártaná pont azt a hibát, amit keres.

A `cap_factory` a hardver-seam (a `FallbackLLMClient(client_factory=...)` mintája).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

JELOLT_ESZKOZOK = 4          # /dev/video0..3 — a Pi-n a webkamera mindig ezek közt van
BEMELEGITO_KOCKAK = 8
BEMELEGITO_SZUNET_S = 0.05


def _cv2_capture(eszkoz: str) -> Any:
    import cv2  # noqa: PLC0415 — lusta: a csomag nehéz, és off-Pi is importálható legyen

    return cv2.VideoCapture(eszkoz)


def elso_kepkocka(eszkoz: str | None = None, *,
                  cap_factory: Callable[[str], Any] | None = None,
                  ) -> tuple[str | None, Any]:
    """(eszköz, kocka) — az ELSŐ eszköz, ami VALÓDI képkockát ad. `(None, None)`, ha egy sem."""
    nyit = cap_factory or _cv2_capture
    jeloltek = [eszkoz] if eszkoz else [f"/dev/video{i}" for i in range(JELOLT_ESZKOZOK)]
    for jelolt in jeloltek:
        cap = nyit(jelolt)
        try:
            if not cap.isOpened():
                continue
            kocka = None
            for _ in range(BEMELEGITO_KOCKAK):
                siker, k = cap.read()
                if siker:
                    kocka = k
                time.sleep(BEMELEGITO_SZUNET_S)
            if kocka is not None:
                return jelolt, kocka
        finally:
            cap.release()
    return None, None


def grab_jpeg(eszkoz: str | None = None, *, minoseg: int = 85,
              cap_factory: Callable[[str], Any] | None = None) -> bytes | None:
    """Egy JPEG, vagy `None`. SOSEM dob — a látás hiánya nem hiba, hanem állapot,
    amit a robot ki tud mondani (ld. a spec §4.5 negatív blokkját)."""
    import cv2  # noqa: PLC0415

    hol, kocka = elso_kepkocka(eszkoz, cap_factory=cap_factory)
    if kocka is None:
        log.info("nincs képkocka: egyetlen /dev/video* sem adott képet")
        return None
    siker, buf = cv2.imencode(".jpg", kocka, [int(cv2.IMWRITE_JPEG_QUALITY), minoseg])
    if not siker:
        log.warning("a képkocka JPEG-re kódolása nem sikerült (%s)", hol)
        return None
    return bytes(buf)
