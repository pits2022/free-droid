"""GPIO pin map (BCM numbering).

These are concrete hardware facts, not implementation. If the wiring changes,
change it here only.

FIGYELEM: ez a fájl korábban azt írta, hogy "verbatim from docs/free-droid.md" — és
hűen át is vette a spec HIBÁS motor-lábait. 2026-08-13-án, az első motor-teszt előtt
derült ki, hogy a specben négyből három motor-láb rossz. A hivatkozási pont ezért
mostantól a HARDVER dokumentációja (`docs/Hat-MDD10 User's Manual.md`) és a gyártó
példakódja, nem a spec — a spec ezekhez igazodott, nem fordítva.
"""

# --- Motors: Cytron HAT-MDD10 ---
#
# EZEK A LÁBAK NEM VÁLASZTHATÓK. A HAT a 40-pines fejlécre ül (nálunk szalagkábellel),
# a vezetékezés a lapon van rézben. A gyártói doksi 6. szakasza és a példakód
# (github.com/CytronTechnologies/Cytron_MDD10_Hat, HatMDD10SM.py) SZÓ SZERINT egyezik:
#     AN1 = 12 (PWM1)   DIG1 = 26 (DIR1)   -> Motor 1
#     AN2 = 13 (PWM2)   DIG2 = 24 (DIR2)   -> Motor 2
#
# A korábbi érték háromból három lábon tévedett (DIR1=13, PWM2=6, DIR2=5), és a
# következmények nem elméletiek voltak:
#   - a "bal irány"-t GPIO13-ra írva valójában a PWM2-t vezéreltük, azaz a MÁSIK
#     motor SEBESSÉG-bemenetét: egy irányváltás megpörgette volna a jobb lánctalpat;
#   - a GPIO6/GPIO5 nincs a HAT-en, tehát a jobb motor a szándékolt lábakra soha
#     nem reagált volna — a hiba "a motor nem megy" tünetként jelentkezett volna,
#     miközben a valódi ok egy másik motor váratlan mozgása.
LEFT_MOTOR_PWM = 12   # pin 32 — HAT PWM1 (Motor 1 speed)
LEFT_MOTOR_DIR = 26   # pin 37 — HAT DIR1 (Motor 1 direction)
RIGHT_MOTOR_PWM = 13  # pin 33 — HAT PWM2 (Motor 2 speed)
RIGHT_MOTOR_DIR = 24  # pin 18 — HAT DIR2 (Motor 2 direction)

# KALIBRÁCIÓS TÉTELEK, amiket a lábkiosztás NEM dönt el — csak a fizikai bekötés:
#
#   1. MELYIK motor a bal? A HAT "Motor 1"-e az, amelyik az M1A/M1B kimenetre van
#      csavarozva. Ha a próbán a "bal" a jobb lánctalpat hajtja, a két PWM/DIR PÁRT
#      kell itt megcserélni (nem a lábakat egyenként!).
#   2. MERRE az "előre"? A doksi truth table-je szerint DIR=Low -> Output A High, de
#      hogy az előre vagy hátra visz, a motor két vezetékének sorrendjén múlik
#      ("CW or CCW depending on the connection" — gyártói komment). Ha fordítva megy,
#      a FORWARD_LEVEL cserélendő.
#
# Mindkettő MÉRÉSSEL dől el, felpolcolt robotnál: scripts/motor_test.py.
FORWARD_LEVEL = 0     # a DIR láb logikai szintje az "előre" irányhoz

# A Sign-Magnitude mód TUDATOS választás, nem a lap "felismeri". A doksi egyetlen fix
# truth table-t ad, a két "mód" csak kétféle használati minta ugyanezen a két lábon:
#
#     PWM   DIR        Output A   Output B
#     Low   mindegy    Low        Low        <-- FELTÉTEL NÉLKÜLI megállás
#     High  Low        High       Low
#     High  High       Low        High
#
# Sign-Magnitude-ban a `PWM = 0` a DIR állapotától FÜGGETLENÜL megállít — ezért a
# `stop()` egyetlen írás egyetlen lábra. Locked-Antiphase-ben a megállás 50%-os
# kitöltés, azaz "álló" állapotban is aktívan helyes jelet kell adni: egy elhalt
# folyamat vagy megcsúszott PWM MOZGÁST jelentene. A biztonsági watchdog (külön szál,
# az LLM-től független) csak az első mód mellett tud egyértelműen megállítani.
PWM_FREQ_HZ = 1000    # a doksi max 20 kHz-et engedélyez; a gyártói példa 100 Hz

# --- Servos: PCA9685 over I2C (camera pan/tilt) ---
I2C_SDA = 2           # pin 3
I2C_SCL = 3           # pin 5
PCA9685_ADDR = 0x40
PAN_CHANNEL = 0       # CH0
TILT_CHANNEL = 1      # CH1

# --- Ultrasonic: HC-SR04P (trig, echo), BCM pins ---
# Front + front-left 45° + front-right 45°. No rear sensor (spec decision).
#
# ⚠️ FELÜLVIZSGÁLANDÓ, MIELŐTT BEKÖTIK (2026-08-13, még egy szenzor sincs bekötve).
# A régi kiosztás hat lábból NÉGYEN ütközik, és mindegyik más eszközzel:
#   front.echo    = 24  -> a HAT DIR2-je. KÉT KIMENET EGY VEZETÉKEN, és pont az
#                          ELÜLSŐ szenzoron, ami A biztonsági érzékelő: a watchdog a
#                          motor irányvezetékét olvasná, miközben a motorok járnak.
#   front_left.echo = 8 -> SPI0 CE0, amit a WS2812 (/dev/spidev0.0) foglal.
#   front_right.trig = 7 -> SPI0 CE1.
#   front_right.echo = 1 -> ID_SC (GPIO0/1 a HAT-azonosító EEPROM lábai; HAT-tal a
#                          fejlécen ezekhez nem szabad hozzányúlni).
# A LÁBAK MÁR ÁT VANNAK ÍRVA az ütközésmentes kiosztásra — nem javaslatként, mert a
# `test_no_duplicate_gpio_assignments` a HAT DIR2 (GPIO24) miatt AZONNAL vörösre váltott,
# és egy hardver-configban a vörös teszt nem hagyható. Kerüli a HAT-ot (12/13/24/26), az
# I2C-t (2/3), az SPI0-t (8/9/10/11), az UART-ot (14/15), a CE1-et (7) és az ID EEPROM-ot
# (0/1). MIVEL MÉG EGY SZENZOR SEM VAN BEKÖTVE, ez most ingyen van — de a bekötésnél EZEK
# a számok érvényesek, nem a spec régi táblája.
ULTRASONIC = {
    "front":      {"trig": 23, "echo": 22},   # pins 16 / 15
    "front_left": {"trig": 27, "echo": 17},   # pins 13 / 11
    "front_right": {"trig": 5, "echo": 6},    # pins 29 / 31  (a régi, hibás motor-lábak)
}

# --- WS2812 status LED ring: SPI0 MOSI ---
WS2812_SPI_DEVICE = "/dev/spidev0.0"  # GPIO10 / pin 19
