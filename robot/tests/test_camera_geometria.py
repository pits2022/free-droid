"""A kamera-geometria: szög -> pulzus, és a biztonsági sáv.

Hardver nélkül ez az EGYETLEN ellenőrizhető része a modulnak (a többi az I2C-buszon
dől el), és pont ez az, ami némán tud rosszul viselkedni: a rossz vágás nem kivételt
ad, hanem egy mozdulatlan kamerát.
"""

from __future__ import annotations

import pytest

from freedroid.camera import pulzus_ms, szog_hatarok, tengelyek, vagott_szog
from freedroid.config.settings import CameraSettings

CFG = CameraSettings()
PAN, TILT = tengelyek(CFG)


def test_a_kozep_a_kozepso_pulzus():
    assert pulzus_ms(PAN, 0.0) == pytest.approx(PAN.centre_ms)


def test_a_szog_a_kalibraciobol_szamol():
    """A kitérés a KALIBRÁCIÓBÓL jön, nem beégetett számból: ha a `ms_per_deg` változik
    (márpedig változott, 0,010 -> 0,020), a pulzus vele mozdul."""
    assert pulzus_ms(PAN, 20.0) == pytest.approx(PAN.centre_ms + 20 * PAN.ms_per_deg)
    assert pulzus_ms(PAN, -20.0) == pytest.approx(PAN.centre_ms - 20 * PAN.ms_per_deg)


def test_a_hatarok_a_biztonsagi_savbol_jonnek():
    also, felso = szog_hatarok(PAN)
    assert pulzus_ms(PAN, also) == pytest.approx(CFG.min_ms)
    assert pulzus_ms(PAN, felso) == pytest.approx(CFG.max_ms)


def test_a_ket_tengely_KULON_kalibraciot_kap():
    """MÉRVE 2026-08-25: a két szervó skálája 19%-kal eltér, és a középük sem egyezik.
    Egy közös értékkészlet az egyikre biztosan hazudna."""
    assert PAN.ms_per_deg != TILT.ms_per_deg
    assert PAN.centre_ms != TILT.centre_ms
    assert PAN.csatorna != TILT.csatorna


def test_a_hatarok_ASZIMMETRIKUSAK_ha_a_kozep_nem_kozepen_van():
    """A pan közepe 1,65 ms a 0,60-2,40-es sávban: lefelé több hely van, mint fölfelé.
    Egy szimmetrikusnak feltételezett tartomány itt az egyik irányban túllőne."""
    also, felso = szog_hatarok(PAN)
    assert abs(also) > abs(felso)


def test_a_vagas_SZOGBEN_tortenik_nem_pulzusban():
    """Ez a teszt lényege, és nem stílus-kérdés.

    Ha csak a PULZUS volna vágva, a nyilvántartott szög elszállna a fizikai határon
    túlra: három "balra 45" után a szoftver 135 fokot hinne, és a rákövetkező
    "jobbra 10" NEM mozdítaná meg a kamerát (125 fok még mindig a határon kívül).
    A robot ilyenkor néma és mozdulatlan — a demón megkülönböztethetetlen egy döglött
    szervótól. Szögben vágva a határról az első ellenirányú parancs elmozdul.
    """
    _, felso = szog_hatarok(PAN)
    szog = 0.0
    for _ in range(3):
        szog = vagott_szog(PAN, szog + 45.0)
    assert szog == pytest.approx(felso)          # a határon áll, nem azon túl
    assert vagott_szog(PAN, szog - 10.0) < felso  # és onnan VAN visszaút


def test_a_kalibracio_atskalazza_a_szoget():
    """A `ms_per_deg` a valódi kalibrációs gomb: ugyanaz a fok más pulzust ad."""
    finomabb, _ = tengelyek(CameraSettings(pan_ms_per_deg=PAN.ms_per_deg / 2))
    assert pulzus_ms(finomabb, 20.0) == pytest.approx(PAN.centre_ms + 20 * PAN.ms_per_deg / 2)
    # a PULZUS-sáv ugyanaz marad, tehát a szög-határ pont kétszeresére TÁGUL
    assert szog_hatarok(finomabb)[1] == pytest.approx(2 * szog_hatarok(PAN)[1])


# --- a lassú pásztázás lépés-felbontása ---

def test_a_lepesek_osszege_PONTOSAN_a_kert_szog():
    """A gesztus végén a kamerának oda kell visszaállnia, ahonnan indult — egy
    lebegőpontos maradék minden pásztázásnál elcsúsztatná."""
    from freedroid.camera import lepesekre
    assert sum(lepesekre(20.0, 2.0)) == pytest.approx(20.0)
    assert sum(lepesekre(7.0, 2.0)) == pytest.approx(7.0)   # nem osztható


def test_egyik_lepes_sem_nagyobb_a_kertnel():
    """Ha egy lépés túllőne, a szervó odaugrana — pont a gyorsaság, ami ellen ez készült."""
    from freedroid.camera import lepesekre
    assert all(lep <= 2.0 + 1e-9 for lep in lepesekre(7.0, 2.0))
    assert len(lepesekre(7.0, 2.0)) == 4        # ceil(7/2)


def test_a_nulla_es_a_negativ_nem_mozdit():
    from freedroid.camera import lepesekre
    assert lepesekre(0.0, 2.0) == []
    assert lepesekre(-5.0, 2.0) == []
