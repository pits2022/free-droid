"""A watchdog KÉT szabálya, hardver nélkül.

A GPIO-t igénylő rész a `test_phase4_hardware.py`-ban van (Pi-only). Ami itt van, az a
két DÖNTÉS — irány-függő megállás és min(3) —, és pont ezek azok, amiket egy elrontott
refaktor csendben visszafordíthat.
"""

from __future__ import annotations

import math

import pytest

from freedroid.config import gpio as G
from freedroid.motion import run_seconds
from freedroid.motion.types import Direction
from freedroid.safety import FRONT, REAR, relevant_sensors
from freedroid.safety.ranging import MIN_SAMPLES, combine


class TestIranyFuggoMegallas:
    def test_elore_csak_az_elulso_allit_meg(self):
        assert relevant_sensors(Direction.FORWARD) == {FRONT}

    def test_hatra_csak_a_hatso_allit_meg(self):
        # Ez a szabály lényege: háttal a falnak a robot EL TUD indulni előre.
        assert relevant_sensors(Direction.BACKWARD) == {REAR}

    def test_ismeretlen_irany_eseten_mindketto(self):
        # Fail-safe: a hiba a felesleges fékezés felé essen, ne a mozgás felé.
        assert relevant_sensors(None) == set(G.ULTRASONIC)

    def test_fordulas_kozben_egyik_sem(self):
        # Ismert vak eset: a súrolt ívet egyik szenzor sem látja, a megállás nem védene,
        # csak megtiltaná a faltól való elfordulást.
        assert relevant_sensors(None, turning=True) == set()

    def test_minden_figyelt_szenzor_letezik_a_kiosztasban(self):
        # Elgépelt szenzornév némán "soha nem állít meg"-et jelentene.
        for heading in (Direction.FORWARD, Direction.BACKWARD, None):
            assert relevant_sensors(heading) <= set(G.ULTRASONIC)


class TestMin3:
    def test_a_veszelyes_kilenges_kiesik(self):
        # A terhelés csak HOSSZABBNAK mutathatja az impulzust: a 73.5 cm-es túlbecslés
        # (a mért legrosszabb eset) a min() miatt nem dönt.
        assert combine([20.0, 93.5, 20.4]) == 20.0

    def test_a_nema_minta_kimarad_de_nem_nullaz(self):
        assert combine([None, 30.0, None]) == 30.0

    def test_csupa_nema_az_None(self):
        # A hívó ezt HIBAKÉNT kezeli (akadály), nem "szabad az út"-ként.
        assert combine([None, None, None]) is None

    def test_ures_ter_szabad_marad(self):
        assert combine([math.inf, math.inf, math.inf]) == math.inf

    def test_harom_minta_a_minimum(self):
        # Mérésből jött szám (docs/free-droid.md 5.), nem ízlés — ne csökkenjen.
        assert MIN_SAMPLES >= 3


class TestMenetido:
    def test_fel_kitoltessel_ketszer_annyi_ido(self):
        assert run_seconds(100, 30.0, 1.0) == pytest.approx(100 / 30.0)
        assert run_seconds(100, 30.0, 0.5) == pytest.approx(2 * 100 / 30.0)

    def test_nulla_kitoltes_hangosan_bukik(self):
        # Különben a robot "megy 2 métert" 0 sebességgel, örökre.
        with pytest.raises(ValueError):
            run_seconds(100, 30.0, 0.0)
