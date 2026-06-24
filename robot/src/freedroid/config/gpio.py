"""GPIO pin map (BCM numbering) — verbatim from docs/free-droid.md.

These are concrete hardware facts, not implementation. If the wiring changes,
change it here only.
"""

# --- Motors: Cytron HAT-MDD10 ---
LEFT_MOTOR_PWM = 12   # pin 32 — left speed
LEFT_MOTOR_DIR = 13   # pin 33 — left direction
RIGHT_MOTOR_PWM = 6   # pin 31 — right speed
RIGHT_MOTOR_DIR = 5   # pin 29 — right direction

# --- Servos: PCA9685 over I2C (camera pan/tilt) ---
I2C_SDA = 2           # pin 3
I2C_SCL = 3           # pin 5
PCA9685_ADDR = 0x40
PAN_CHANNEL = 0       # CH0
TILT_CHANNEL = 1      # CH1

# --- Ultrasonic: HC-SR04P (trig, echo), BCM pins ---
# Front + front-left 45° + front-right 45°. No rear sensor (spec decision).
ULTRASONIC = {
    "front":      {"trig": 23, "echo": 24},   # pins 16 / 18
    "front_left": {"trig": 25, "echo": 8},    # pins 22 / 24
    "front_right": {"trig": 7, "echo": 1},    # pins 26 / 28
}

# --- WS2812 status LED ring: SPI0 MOSI ---
WS2812_SPI_DEVICE = "/dev/spidev0.0"  # GPIO10 / pin 19
