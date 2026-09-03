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
    assert s.safety.stop_threshold_cm == 35.0   # 2026-09-03: a mért 0,8 duty fékútja miatt (lásd SafetySettings)


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


def test_motion_rejects_negative_coast():
    """A NULLA megengedett (elvben egy azonnal fékező hajtás), a negatív nem: az a
    fékút-büdzsében NEGATÍV utat jelentene, azaz a robot a döntés előtt állna meg."""
    MotionSettings(coast_s=0.0)
    with pytest.raises(ValueError):
        MotionSettings(coast_s=-0.1)


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
    # amit nem írtunk felül, az érintetlen. A KALIBRÁCIÓS ÉRTÉKHEZ mérünk, nem egy
    # beírt számhoz: a `cm_per_s_at_full` MÉRÉS eredménye (2026-08-26 óta 66.6 -> 76.6),
    # és egy ide másolt literál minden újrakalibrálásnál vörösre váltana — anélkül, hogy
    # bármit is mondana arról, amit ez a teszt valójában őriz (a felül NEM írt mező
    # érintetlen marad).
    assert s.motion.cm_per_s_at_full == MotionSettings().cm_per_s_at_full


def test_env_nelkul_az_alapertelmezes_marad():
    s = load_settings({})
    assert s.motion.deg_per_s_at_full == MotionSettings().deg_per_s_at_full
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


def test_a_felismert_kulcsok_keszlete_ROGZITETT():
    """PR #88 review: a mezőket az ANNOTÁCIÓ alapján ismerjük fel, és ez elromolhat.

    Ma minden annotáció sztring (`from __future__ import annotations`). Ha ez az import
    valaha eltűnik, az annotációk típusobjektumok lesznek — és egy sztring-összevetés
    egyetlen mezőre sem illeszkedne, tehát MINDEN felülírás NÉMÁN abbahagyná a
    működését. Ez a teszt akkor is szól, ha a felismerés bármi mástól romlik el.
    """
    from freedroid.config import settings as S

    ismert = set()
    for elonev, (_, cls) in S._SZEKCIOK.items():
        _, kulcsok = S._szekciobol(cls, elonev, {})
        ismert |= kulcsok

    assert {"FREEDROID_LLM_EDGE_MODEL", "FREEDROID_LLM_CLOUD_MODEL",
            "FREEDROID_MOTION_DEG_PER_S_AT_FULL", "FREEDROID_MOTION_RIGHT_DUTY_TRIM",
            "FREEDROID_SAFETY_STOP_THRESHOLD_CM", "FREEDROID_RAG_TOP_K",
            "FREEDROID_RAG_ENABLED"} <= ismert
    # A Mapping mező NEM lehet köztük (env-be sűrített dict némán rossz küszöböt adna).
    assert "FREEDROID_SAFETY_PER_SENSOR_CM" not in ismert


def test_a_tipusfelismeres_a_kiertekelt_annotaciot_is_birja():
    """A javítás lényege: sztring ÉS típusobjektum annotáció is működjön."""
    from freedroid.config.settings import _tipusnev

    assert _tipusnev("float") == "float"
    assert _tipusnev(float) == "float"
    assert _tipusnev(bool) == "bool"
    assert _tipusnev("Mapping[str, float]") not in ("str", "int", "float", "bool")


@pytest.mark.parametrize("nyers", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_a_nem_veges_float_HANGOSAN_bukik(nyers):
    """PR #88 review: a `float()` elfogadja őket, és a NaN MINDEN összehasonlítása
    hamis — tehát a tartomány-ellenőrzés NÉMÁN átengedné.

    A hatás nem ártalmatlan: NaN sebességnél NaN a menetidő, végtelennél NULLA,
    azaz a robot meg sem mozdul. Mindkettő csendben.
    """
    with pytest.raises(ValueError, match="véges számot"):
        load_settings({"FREEDROID_MOTION_CM_PER_S_AT_FULL": nyers})


def test_a_NaN_tenyleg_kicselezne_a_tartomany_ellenorzest():
    """Az ok, amiért a fenti őr KELL — nem elméleti: a dataclass validációja
    `<= 0`-t néz, és a NaN arra hamisat ad."""
    import math

    from freedroid.config.settings import MotionSettings

    assert not (math.nan <= 0)                      # a validáció feltétele HAMIS
    assert MotionSettings(cm_per_s_at_full=math.nan).cm_per_s_at_full != 0  # átmegy rajta


def test_elgepelt_play_command_helyorzo_INDULASKOR_bukik():
    """PR #91 review: a `{rate}`-et a PiperTTS tölti ki. Egy elgépelt felülírás enélkül
    csak a BESZÉD pillanatában bukna ki — vagyis a színpadon."""
    with pytest.raises(ValueError, match="helyőrző"):
        load_settings({"FREEDROID_VOICE_PLAY_COMMAND": "aplay -r {sample_rate}"})
    # a helyes viszont átmegy, és a helyőrző nélküli parancs is (pl. egy fix wrapper)
    assert load_settings({"FREEDROID_VOICE_PLAY_COMMAND": "aplay -r {rate}"}).voice
    assert load_settings({"FREEDROID_VOICE_PLAY_COMMAND": "sajat-lejatszo"}).voice
