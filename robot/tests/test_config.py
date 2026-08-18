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


def test_ultrasonic_sensors_have_distinct_trig_echo():
    assert set(gpio.ULTRASONIC) == {"front", "rear"}
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


# --- env-felülírás (2026-08-18) ---------------------------------------------- #
# MIÉRT LÉTEZIK: enélkül a roboton az egyetlen mód bármit átállítani a FORRÁS
# szerkesztése volt — és az kétszer harapott (blokkolt `git checkout`, a Pi hetekig
# egy régi branchen). A gép-specifikus értéknek nem a verziókövetett fájlban a helye.

def test_env_felulirja_a_szekciok_mezoit():
    s = load_settings({
        "FREEDROID_MOTION_DEG_PER_S_AT_FULL": "300",
        "FREEDROID_LLM_EDGE_MODEL": "szabi-3b-v12",
        "FREEDROID_RAG_TOP_K": "1",
        "FREEDROID_SAFETY_STOP_THRESHOLD_CM": "40",
    })
    assert s.motion.deg_per_s_at_full == 300.0
    assert s.llm.edge_model == "szabi-3b-v12"
    assert s.rag.top_k == 1
    assert s.safety.stop_threshold_cm == 40.0
    # amit nem írtunk felül, az érintetlen
    assert s.motion.cm_per_s_at_full == 66.6


def test_env_nelkul_az_alapertelmezes_marad():
    s = load_settings({})
    assert s.motion.deg_per_s_at_full == 280.0
    assert s.llm.edge_model == "csaba_ajtony/szabi-3b-v12"


def test_a_bool_NEM_a_python_igazsagerteke():
    """`bool("hamis")` Pythonban IGAZ — egy naiv konverzió némán BEkapcsolva hagyná
    a RAG-ot egy `FREEDROID_RAG_ENABLED=hamis` mellett."""
    assert load_settings({"FREEDROID_RAG_ENABLED": "nem"}).rag.enabled is False
    assert load_settings({"FREEDROID_RAG_ENABLED": "igen"}).rag.enabled is True
    with pytest.raises(ValueError, match="logikai"):
        load_settings({"FREEDROID_RAG_ENABLED": "hamis"})


def test_ertelmezhetetlen_ertek_HANGOSAN_bukik():
    with pytest.raises(ValueError, match="nem értelmezhető"):
        load_settings({"FREEDROID_MOTION_DEG_PER_S_AT_FULL": "gyorsan"})


def test_a_validacio_az_env_ertekre_IS_fut():
    """A felülírás nem kerülheti meg a tartomány-ellenőrzést: egy 1.0 fölötti trim
    némán 100%-on telítődne, és a robot ugyanúgy húzna, 'kalibrálva'."""
    with pytest.raises(ValueError, match="lassítani"):
        load_settings({"FREEDROID_MOTION_RIGHT_DUTY_TRIM": "1.5"})


def test_elgepelt_felulirasra_FIGYELMEZTET(capsys):
    """Némán az alapértelmezéssel futni pontosan az a csendes sodródás, ami ellen
    ez az egész készült."""
    load_settings({"FREEDROID_MOTION_DEG_PER_SEC": "99"})
    assert "ISMERETLEN felülírás" in capsys.readouterr().err


def test_a_tobbi_modul_env_valtozoira_NEM_szol(capsys):
    load_settings({"FREEDROID_TRANSCRIPT_LOG": "/tmp/x.jsonl",
                   "FREEDROID_ASSUME_PI": "1"})
    assert capsys.readouterr().err == ""
