"""Config: GPIO pinout sanity + settings validation/immutability."""

from __future__ import annotations

import dataclasses

import pytest

from freedroid.config import gpio
from freedroid.config.settings import (
    LLMEndpoints,
    MotionSettings,
    SafetySettings,
    Settings,
    load_settings,
)


def _all_output_pins() -> list[int]:
    pins = [
        gpio.LEFT_MOTOR_PWM, gpio.LEFT_MOTOR_DIR,
        gpio.RIGHT_MOTOR_PWM, gpio.RIGHT_MOTOR_DIR,
        gpio.I2C_SDA, gpio.I2C_SCL,
    ]
    for s in gpio.ULTRASONIC.values():
        pins += [s["trig"], s["echo"]]
    return pins


def test_no_duplicate_gpio_assignments():
    pins = _all_output_pins()
    dupes = {p for p in pins if pins.count(p) > 1}
    assert not dupes, f"GPIO pins assigned twice: {dupes}"


def test_gpio_pins_in_valid_bcm_range():
    for p in _all_output_pins():
        assert 0 <= p <= 27, f"BCM pin out of range: {p}"


def test_three_ultrasonic_sensors_with_distinct_trig_echo():
    assert set(gpio.ULTRASONIC) == {"front", "front_left", "front_right"}
    for name, s in gpio.ULTRASONIC.items():
        assert s["trig"] != s["echo"], f"{name} trig==echo"


def test_pan_tilt_channels_distinct():
    assert gpio.PAN_CHANNEL != gpio.TILT_CHANNEL


def test_default_settings_load():
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.llm.cloud_url == "http://10.0.0.1:11434"
    assert s.llm.edge_url == "http://127.0.0.1:11434"
    assert s.safety.stop_threshold_cm == 25.0


@pytest.mark.parametrize("bad", [-1.0, 0.0])
def test_safety_rejects_nonpositive_threshold(bad):
    with pytest.raises(ValueError):
        SafetySettings(stop_threshold_cm=bad)


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_motion_rejects_out_of_range_speed(bad):
    with pytest.raises(ValueError):
        MotionSettings(default_speed=bad)


def test_motion_rejects_nonpositive_pwm_freq():
    with pytest.raises(ValueError):
        MotionSettings(pwm_frequency_hz=0)


def test_per_sensor_overrides_are_read_only():
    s = SafetySettings()
    with pytest.raises(TypeError):
        s.per_sensor_cm["front"] = 10.0  # type: ignore[index]


def test_settings_are_frozen():
    s = LLMEndpoints()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.model = "other"  # type: ignore[misc]
