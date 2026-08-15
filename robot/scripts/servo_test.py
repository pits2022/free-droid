#!/usr/bin/env python3
"""Phase 1.5 smoke test — pan/tilt szervók a PCA9685-ön.

CH0 = pan, CH1 = tilt (a freedroid.config.gpio-ból), 50 Hz.

ELSŐ bekapcsolásnál KIS kitéréssel indíts, egy csatornán:

    uv run python scripts/servo_test.py --channel pan --range 0.15
    uv run python scripts/servo_test.py --centre-only     # csak középre áll

MIÉRT: a teljes 1,0-2,0 ms kitérés a szervó VÉGÁLLÁSA. Ha a kamera-tartó mechanikusan
szűkebb, a szervó nekifeszül az ütközőnek és MEGRÁNTOTT áramot vesz fel (MG996R:
~2,5 A/db), miközben a szervó-sín az LM2596-ról jön, ami 2 A-es. Két szervó egyszerre
végállásban tehát a TÁPOT viszi el — és a Pi vele mehet. Kis kitéréssel előbb kiderül,
merre van hely.
"""

from __future__ import annotations

import argparse
import time

from freedroid.config import gpio as G

PERIOD_MS = 20.0  # 50 Hz
CENTRE_MS = 1.5
TELJES_KITERES_MS = 0.5   # a szervó végállása a középtől: 1,0 ms ... 2,0 ms


# PCA9685 regiszterek (datasheet)
_MODE1, _MODE2, _PRESCALE, _LED0_ON_L = 0x00, 0x01, 0xFE, 0x06


def _diagnosztika(i2c, cim: int, csatorna: int) -> None:
    """Megérkezik-e a parancs a chipre — a "nem mozdul" KÉT okának szétválasztása.

    Ha a regiszterekben ott a helyes érték, akkor az I2C-oldal rendben van, és a hiba a
    kimeneten túl keresendő (OE, V+, szervó-bekötés). Ha nincs ott, akkor a parancs nem
    ért oda, és az I2C-t kell nézni.
    """
    def olvas(reg: int, n: int = 1) -> list[int]:
        ki = bytearray(n)
        # Korlátos várakozás: egy szálon a try_lock elsőre sikerül, de a `while ... pass`
        # egy elakadt zárnál egy magot pörget a végtelenségig. Egy MŰSZER ne fagyjon be.
        for _ in range(100):
            if i2c.try_lock():
                break
            time.sleep(0.001)
        else:
            raise RuntimeError("az I2C-buszt 0,1 s alatt sem sikerült lezárni")
        try:
            i2c.writeto_then_readfrom(cim, bytes([reg]), ki)
        finally:
            i2c.unlock()
        return list(ki)

    # A BUSZ MEGBÍZHATÓSÁGA — ez az ELSŐ mérés, mert egy szakaszos kapcsolat MINDEN
    # további leletet meghamisít: a félbeszakadt írástól a MODE1 tetszőleges értéket
    # vehet fel (pl. beragadt SLEEP bit), és a szoftvert okoljuk érte. Ha a regisztereket
    # olvasnánk előbb, egy `Errno 121` KIVÉTELKÉNT szállna el — a busz-próba, ami épp ezt
    # magyarázná meg, le sem futna.
    # MÉRVE 2026-08-14: a chip előbb hibátlanul válaszolt, majd `OSError: [Errno 121]
    # Remote I/O`-t adott, végül a busz be is akadt — miközben a kód nem változott.
    print(f"\n=== PCA9685 diagnosztika (cím {cim:#04x}, CH{csatorna}) ===")
    hiba = 0
    for _ in range(30):
        try:
            olvas(_MODE1)
        except OSError:
            hiba += 1
    print(f"busz-próba: 30 olvasásból HIBÁS: {hiba}")
    if hiba:
        print("  -> SZAKASZOS AZ I2C-KAPCSOLAT. Minden további lelet gyanús: egy félbeszakadt")
        print("     írás a MODE1-et is elállíthatja. Előbb a VEZETÉKEKET nézd (SDA/SCL")
        print("     jumperek ülése, breadboard-sorok), csak utána a szoftvert.")
        return

    mode1, mode2 = olvas(_MODE1)[0], olvas(_MODE2)[0]
    prescale = olvas(_PRESCALE)[0]
    on_l, on_h, off_l, off_h = olvas(_LED0_ON_L + 4 * csatorna, 4)
    off = off_l | (off_h << 8)

    print(f"\n--- regiszterek (CH{csatorna}) ---")
    print(f"MODE1    = {mode1:#04x}   SLEEP={'IGEN (a chip ALSZIK!)' if mode1 & 0x10 else 'nem'}"
          f"  ALLCALL={'be' if mode1 & 0x01 else 'ki'}")
    print(f"MODE2    = {mode2:#04x}   kimenet={'totem-pole' if mode2 & 0x04 else 'OPEN-DRAIN'}"
          f"  INVRT={'IGEN' if mode2 & 0x10 else 'nem'}")
    print(f"PRESCALE = {prescale}      (50 Hz-hez 121 körül kell lennie)")
    # A REGISZTER 12 BITES, a könyvtár `duty_cycle` tulajdonsága 16 bites: 16-tal osztva
    # ír. 1,5 ms 50 Hz-en = 7,5% = 0,075 * 4096 = 307. (Az első változatom itt 4915-öt
    # várt — 16 bites értéket hasonlított 12 bites regiszterhez, és HELYES beállításra
    # mondta volna, hogy hibás.)
    print(f"CH{csatorna} OFF   = {off}      (1,5 ms középhez 307 a 12 bites regiszterben)")

    if mode1 & 0x10:
        print("\n  -> A CHIP ALSZIK: a kimenetek nem működnek. A frekvencia-állítás után")
        print("     nem ébredt fel — driver-hiba vagy megszakadt I2C-írás.")
    elif not (mode2 & 0x04):
        print("\n  -> OPEN-DRAIN kimeneti mód: a szervó jelvezetéke nem kap AKTÍV magasat.")
        print("     A szervók totem-pole kimenetet igényelnek.")
    elif off == 0:
        print("\n  -> A CH regiszter NULLA: a parancs NEM érkezett meg (vagy felülíródott).")
    else:
        print("\n  -> A PARANCS MEGÉRKEZETT, a chip helyesen van beállítva.")
        print("     Ha a szervó mégsem mozdul, a hiba a kimeneten TÚL van:")
        print("       1. OE láb: ha lebeg és a panelen NINCS lehúzó ellenállás, a kimenetek")
        print("          LE VANNAK TILTVA. Klónoknál gyakori. Próbáld OE -> GND.")
        print("       2. V+ (szervó-táp) tényleg ott van a CSATORNA-tűsoron? A sorkapocs és")
        print("          a csatornák V+-a ugyanaz a hálózat — mérd a csatorna középső tűjén.")
        print("       3. A szervó jelvezetéke a 3 tűs csoport HELYES tűjén van-e")
        print("          (barna/fekete=GND, piros=V+, narancs/sárga=jel).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", choices=("pan", "tilt", "both"), default="both",
                    help="melyik szervót mozgassuk (elsőre egyet)")
    ap.add_argument("--range", type=float, default=TELJES_KITERES_MS, metavar="MS",
                    help=f"kitérés a középtől ms-ban (alap: {TELJES_KITERES_MS} = végállás; "
                         f"első bekapcsolásnál 0.15 ajánlott)")
    ap.add_argument("--centre-only", action="store_true",
                    help="csak középre áll és ott marad (a mechanika ellenőrzésére)")
    ap.add_argument("--diag", action="store_true",
                    help="regiszter-szintű ellenőrzés: megérkezik-e a parancs a chipre")
    args = ap.parse_args()
    if not 0 < args.range <= TELJES_KITERES_MS:
        ap.error(f"--range 0 és {TELJES_KITERES_MS} között legyen (ms a középtől)")

    import board
    import busio
    from adafruit_pca9685 import PCA9685

    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c, address=G.PCA9685_ADDR)
    pca.frequency = 50

    def set_pulse(channel: int, ms: float) -> None:
        pca.channels[channel].duty_cycle = int(ms / PERIOD_MS * 0xFFFF)

    csatornak = {"pan": [(G.PAN_CHANNEL, "pan")], "tilt": [(G.TILT_CHANNEL, "tilt")],
                 "both": [(G.PAN_CHANNEL, "pan"), (G.TILT_CHANNEL, "tilt")]}[args.channel]

    # A --diag ág is a try/finally-n BELÜL: e nélkül egy kivétel a diagnosztikában
    # kihagyta a `pca.deinit()`-et, és a PWM TOVÁBB MENT — a szervó a hiba pillanatában
    # felvett pozícióban feszül tovább. Pont a "nekifeszül az ütközőnek" eset.
    try:
        if args.diag:
            diag_ch = G.PAN_CHANNEL if args.channel != "tilt" else G.TILT_CHANNEL
            set_pulse(diag_ch, CENTRE_MS)
            time.sleep(0.2)
            _diagnosztika(i2c, G.PCA9685_ADDR, diag_ch)
            return 0

        for channel, label in csatornak:
            print(f"{label} (CH{channel}) -> KÖZÉP ({CENTRE_MS} ms)")
            set_pulse(channel, CENTRE_MS)
            time.sleep(0.6)
            if args.centre_only:
                continue
            # Középről indul és oda is tér vissza: az ütközőnek feszülés esélye így a
            # legkisebb, és minden lépés után van egy ismert, biztonságos állapot.
            for ms in (CENTRE_MS - args.range, CENTRE_MS,
                       CENTRE_MS + args.range, CENTRE_MS):
                print(f"  {ms:.2f} ms")
                set_pulse(channel, ms)
                time.sleep(0.5)
        print(f"OK — {args.channel} kész (kitérés ±{args.range} ms). Amit fel kell írni: "
              f"MOZDULT-e, MERRE, és nem feszül-e neki valaminek a végén.")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        pca.deinit()


if __name__ == "__main__":
    raise SystemExit(main())
