"""A `home()` őre: a kör eleji alaphelyzet ne legyen körönkénti rándulás.

🔴 MÉRVE 2026-09-09, élő menetben: a holtjáték-kompenzáció FELTÉTEL NÉLKÜL alálő a
hézagnyit (pan 10, tilt 5 fok), majd visszaáll a célra. A `home()` a kör elején fut
(#125), tehát MINDEN FIGYELJ-nél lement ez az oda-vissza — akkor is, ha a fej már
0/0-ban állt. A Teremtő ezt „a kamera pásztáz egyet"-ként látta.

A `PanTiltCamera` konstruktora Pi-only (I2C, PCA9685), ezért a példány `object.__new__`-val
készül, és csak a mért ág (`_kiad`) van kicserélve — a vizsgált logika a VALÓDI kód.
Ugyanaz a fogás, mint a `test_safety_policy.py`-ban.
"""

from __future__ import annotations

from freedroid.camera import CameraAction, PanTiltCamera, tengelyek
from freedroid.config.settings import load_settings


def kamera() -> tuple[PanTiltCamera, list[tuple[str, float]]]:
    """Egy hardver nélküli kamera + a KIADOTT szögek listája."""
    cfg = load_settings().camera
    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = set()
    kiadva: list[tuple[str, float]] = []
    k._kiad = lambda t, szog: kiadva.append((t.nev, szog))  # type: ignore[method-assign]
    return k, kiadva


def test_az_ELSO_home_valodi_mozdulat():
    """A konstruktor kompenzáció NÉLKÜL ad ki 0-t, tehát a fogak abból az irányból
    feszülnek, amerről a szervo érkezett. Az első `home()` nem hagyható ki."""
    k, kiadva = kamera()
    k.home()
    assert kiadva, "az első home() nem mozdított semmit"
    # alálövés MINDKÉT tengelyen, majd a 0
    assert [szog for _, szog in kiadva if szog != 0.0], kiadva
    assert k._tiszta == {"pan", "tilt"}


def test_a_MASODIK_home_nem_mozdit():
    """Ez a bejelentett hiba: körönkénti rándulás úgy, hogy nincs mit helyrehozni."""
    k, _ = kamera()
    k.home()
    _, kiadva = k, []
    k._kiad = lambda t, szog: kiadva.append((t.nev, szog))  # type: ignore[method-assign]
    k.home()
    assert kiadva == [], f"a második home() mozdított: {kiadva}"


def test_egy_pan_UTAN_a_home_megint_mozdit():
    """Az őr nem néma no-op: a relatív `pan`/`tilt` halmozódik, azt vissza KELL hozni."""
    k, _ = kamera()
    k.home()
    k.pan("left", 30)
    assert k._tiszta != {"pan", "tilt"}
    kiadva: list[tuple[str, float]] = []
    k._kiad = lambda t, szog: kiadva.append((t.nev, szog))  # type: ignore[method-assign]
    k.home()
    assert kiadva, "a pan után a home() nem állította vissza a fejet"
    assert k._szog == {"pan": 0.0, "tilt": 0.0}


def test_egy_gesztus_UTAN_nem_kell_ujabb_home():
    """A `nod` a `finally`-ban a KOMPENZÁLT úton tér vissza a kiindulóba, tehát ha az
    0/0 volt, a fej tisztán áll — a következő kör `home()`-ja fölösleges volna."""
    k, _ = kamera()
    k.home()
    k.action(CameraAction.NOD)
    assert k._szog == {"pan": 0.0, "tilt": 0.0}
    kiadva: list[tuple[str, float]] = []
    k._kiad = lambda t, szog: kiadva.append((t.nev, szog))  # type: ignore[method-assign]
    k.home()
    assert kiadva == [], f"a gesztus után a home() fölöslegesen mozdított: {kiadva}"
