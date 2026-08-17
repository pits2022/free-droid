"""HC-SR04 távolságmérés — a MÉRT, bevált eljárás egyetlen példányban.

Ez a kód a `scripts/ultrasonic_test.py`-ban született, és ott mérte ki magát 2026-08-15-én
(trigger-szélesség, időtúllépés, hatótáv). A watchdog nem írhatja újra: a szenzoros mérés
minden számát drágán fizettük ki, és két másolat előbb-utóbb szétcsúszik. A script most
innen importál.
"""

from __future__ import annotations

import math
import time

SOUND_CM_PER_S = 34300.0

# A HC-SR04 "nincs visszhang" jelzése egy ~38 ms-os MAGAS impulzus (datasheet). A régi
# 40 ms-os ablak ezt épphogy elvágta, és a mérés a saját időtúllépését számolta
# távolsággá: "40002 us -> 686.0 cm". 60 ms-mal a 38 ms-os impulzus BEFEJEZETTKÉNT
# látszik, tehát megkülönböztethető a valódi méréstől.
TIMEOUT_S = 0.06

# A szenzor fizikai hatótávja ~4 m. Ami e fölött jönne, az NEM mérés, hanem a "nincs
# visszhang" jelzés félreolvasása — ezért a mérés inkább None-t ad, mint egy hihető,
# de hamis számot.
MAX_RANGE_CM = 450.0

# Hány mérés min()-ét vesszük egy döntéshez. MÉRÉSSEL indokolt szám, nem ízlés:
# terhelés alatt egyetlen mérés legrosszabb kihagyása 4283 us volt (73,5 cm TÚLbecslés),
# 20 Hz-en ~45 másodpercenként egy hamis "szabad az út". A hiba EGYIRÁNYÚ — az ütemező
# csak HOSSZABBNAK mutathatja az impulzust —, ezért a min() pontosan a veszélyes
# kilengéseket dobja el, és mindháromnak egyszerre kellene elromlania (1,4e-9).
# Lásd docs/free-droid.md 5. szakasz. NE csökkentsd 3 alá.
MIN_SAMPLES = 3


def trigger(lgpio, h, trig: int) -> None:
    """~12 us-os trigger-impulzus, PONTOSAN időzítve (busy-wait, nem sleep).

    A `time.sleep(1e-5)` Linuxon nem 10 us-ot alszik: a felébresztés szemcsézettsége
    miatt tipikusan 60-100+ us lesz belőle. A datasheet 10 us MINIMUMOT ír, tehát a
    hosszabb impulzus elvben rendben van — de a klónok itt eltérnek.
    """
    lgpio.gpio_write(h, trig, 0)
    time.sleep(0.002)
    lgpio.gpio_write(h, trig, 1)
    veg = time.perf_counter() + 12e-6
    while time.perf_counter() < veg:
        pass
    lgpio.gpio_write(h, trig, 0)


def measure_cm(lgpio, h, trig: int, echo: int) -> float | None:
    """EGY mérés. Háromféle kimenet, és a különbség NEM kozmetikai:

    * `float`  — mért távolság cm-ben.
    * `inf`    — a szenzor VÁLASZOLT, de nincs semmi a hatótávon belül. SZABAD az út.
    * `None`   — az Echo meg sem szólalt: néma szenzor (szakadt vezeték, nincs táp,
                 rossz láb). Ez HIBA, nem "szabad az út".

    A kettő szétválasztása azért kell, mert egy üres teremben a HC-SR04 a normális
    működése szerint ad "nincs visszhang" jelzést (~38 ms-os impulzus). Ha ezt a
    watchdog akadálynak venné, a robot egy ÜRES teremben nem tudna elindulni; ha
    viszont a néma szenzort venné szabad útnak, egy szakadt föld-vezeték (ez már
    megtörtént, 2026-08-15) csendben vakká tenné. A régi közös `None` mindkét hibát
    lehetővé tette.

    Biztonsági döntéshez ne ezt hívd közvetlenül, hanem a `measure_cm_min3`-at.
    """
    trigger(lgpio, h, trig)

    start = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 0:
        if time.perf_counter() - start > TIMEOUT_S:
            return None  # az Echo fel sem futott -> néma szenzor
    rise = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 1:
        if time.perf_counter() - rise > TIMEOUT_S:
            return None  # sosem esett vissza -> beragadt láb, szintén hiba
    cm = (time.perf_counter() - rise) * SOUND_CM_PER_S / 2.0
    return math.inf if cm > MAX_RANGE_CM else cm


def combine(samples: list[float | None]) -> float | None:
    """A min(3) szabály — a mérésektől ELKÜLÖNÍTVE, hogy hardver nélkül is tesztelhető.

    A `None` (néma szenzor) nem érték, hanem hiányzó mérés: kihagyjuk. Ha MINDEGYIK
    minta None, az eredmény is None — a hívónak azt hibaként kell kezelnie.
    """
    valid = [s for s in samples if s is not None]
    return min(valid) if valid else None


def measure_cm_min3(lgpio, h, trig: int, echo: int, samples: int = MIN_SAMPLES) -> float | None:
    """A biztonsági döntéshez használt mérés: `samples` mérés min()-e."""
    return combine([measure_cm(lgpio, h, trig, echo) for _ in range(samples)])
