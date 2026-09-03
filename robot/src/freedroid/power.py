"""Akku-feszültség az ADS1115-ről, KÖNYVTÁR NÉLKÜL.

ponytail: nincs smbus/adafruit-ads1x15 — egy 3 bájtos írás és egy 2 bájtos olvasás
a `/dev/i2c-1`-en, `ioctl(I2C_SLAVE)`-vel. Ugyanaz az elv, mint a kattintónál: egy
C-kiterjesztés egy regiszterolvasásért nem éri meg.

Az ADS1115 (TI adatlap): 0x01 = config regiszter, 0x00 = konverziós regiszter, mindkettő
16 bites, MSB először. A config 0xC183: OS=1 (egyszeri konverzió indul), MUX=100 (AIN0 a
GND-hez), PGA=000 (±6,144 V, 1 LSB = 187,5 µV), MODE=1 (egyszeri), 128 SPS, komparátor ki.
128 SPS-nél a konverzió 7,8 ms — a 10 ms-os várakozás elég, az OS-bit pollozása nem kell.
"""

from __future__ import annotations

import fcntl
import os
import time

from freedroid.config.settings import PowerSettings

I2C_SLAVE = 0x0703          # linux/i2c-dev.h
_CONFIG_AIN0_6V = bytes([0x01, 0xC1, 0x83])
_LSB_V = 6.144 / 32768     # 187,5 µV: a ±FSR 2^15 lépés (adatlap; PR #103 review)


def volt_from_raw(hi: int, lo: int, divider: float) -> float:
    """Konverziós regiszter (2 bájt, MSB először) -> akkufeszültség. Külön, hogy
    tesztelhető legyen I2C nélkül."""
    raw = int.from_bytes(bytes([hi, lo]), "big", signed=True)
    return raw * _LSB_V * divider


def read_battery_v(s: PowerSettings) -> float:
    """Egy mérés. `OSError`-t dob, ha nincs busz/eszköz — a hívó dönti el, mit ér az."""
    fd = os.open(s.i2c_bus, os.O_RDWR)
    try:
        fcntl.ioctl(fd, I2C_SLAVE, s.ads_address)
        os.write(fd, _CONFIG_AIN0_6V)
        time.sleep(0.01)
        os.write(fd, bytes([0x00]))
        adat = os.read(fd, 2)
    finally:
        os.close(fd)
    # Rövid olvasás -> OSError, NEM ValueError: a hívók (health, orchestrator) csak
    # OSError-t kapnak el, egy csonka busz-válasz különben a főhurkot vinné el.
    # (PR #103 review.)
    if len(adat) < 2:
        raise OSError(f"csonka I2C-olvasás az ADS1115-ről: {len(adat)} bájt 2 helyett")
    return volt_from_raw(adat[0], adat[1], s.divider)
