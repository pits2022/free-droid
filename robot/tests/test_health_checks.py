"""Individual checks — driven by monkeypatched probes (no real hardware/network).

The key behaviours: cloud failures are WARNING (edge fallback), edge/hardware
failures are CRITICAL with remediation where applicable, hardware checks SKIP off-Pi.
"""

from __future__ import annotations

import pytest

from freedroid.config.settings import load_settings
from freedroid.health import checks
from freedroid.health.model import Severity, Status


@pytest.fixture
def settings():
    return load_settings()


# --- network: cloud is non-vital ------------------------------------------- #
def test_cloud_ollama_ok(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (200, ""))
    r = checks.check_cloud_ollama(settings)
    assert r.status is Status.OK


def test_cloud_ollama_unreachable_is_warning_not_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (0, ""))
    r = checks.check_cloud_ollama(settings)
    assert r.status is Status.WARN
    assert r.severity is Severity.WARNING
    assert not r.is_critical_failure


# --- software: edge brain is vital ----------------------------------------- #
def test_edge_ollama_down_is_critical_with_remediation(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (0, ""))
    r = checks.check_edge_ollama(settings)
    assert r.is_critical_failure
    assert r.remediation == "restart_ollama"


def test_edge_model_present(monkeypatch, settings):
    body = '{"models": [{"name": "llama3.2:3b"}]}'
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (200, body))
    r = checks.check_edge_model(settings)
    assert r.status is Status.OK


def test_edge_model_missing_is_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (200, '{"models": []}'))
    r = checks.check_edge_model(settings)
    assert r.is_critical_failure


def test_edge_model_skipped_when_ollama_down(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda url, **k: (0, ""))
    assert checks.check_edge_model(settings).status is Status.SKIPPED


# --- hardware: skipped off-Pi ---------------------------------------------- #
@pytest.mark.parametrize("check", [
    checks.check_gpio_chip, checks.check_i2c_bus, checks.check_audio_input,
    checks.check_orchestrator_service,
])
def test_hardware_and_service_checks_skip_off_pi(monkeypatch, settings, check):
    monkeypatch.setattr(checks, "is_pi", lambda: False)
    assert check(settings).status is Status.SKIPPED


def test_gpio_chip_fail_on_pi_is_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks.glob, "glob", lambda pat: [])
    r = checks.check_gpio_chip(settings)
    assert r.is_critical_failure


def test_audio_input_missing_on_pi_is_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "run", lambda cmd, **k: (127, "", "no arecord"))
    assert checks.check_audio_input(settings).is_critical_failure


def test_orchestrator_active_on_pi_is_ok(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "run", lambda cmd, **k: (0, "active\n", ""))
    assert checks.check_orchestrator_service(settings).status is Status.OK


def test_orchestrator_inactive_is_critical_with_remediation(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "run", lambda cmd, **k: (3, "inactive\n", ""))
    r = checks.check_orchestrator_service(settings)
    assert r.is_critical_failure and r.remediation == "restart_orchestrator"


def test_package_import_ok(settings):
    assert checks.check_package_import(settings).status is Status.OK


def test_registry_covers_all_layers(settings):
    from freedroid.health.model import Layer
    layers = {c(settings).layer for c in checks.ALL_CHECKS}
    assert layers == {Layer.NETWORK, Layer.HARDWARE, Layer.SOFTWARE}


# --- network: wireguard interface (cloud link → WARNING) -------------------- #
def test_wireguard_absent_is_warning_with_remediation(monkeypatch, settings):
    monkeypatch.setattr(checks, "path_exists", lambda p: False)
    r = checks.check_wireguard_interface(settings)
    assert r.status is Status.FAIL and r.severity is Severity.WARNING
    assert r.remediation == "restart_wireguard"
    assert not r.is_critical_failure


def test_wireguard_up_is_ok(monkeypatch, settings):
    monkeypatch.setattr(checks, "path_exists", lambda p: True)
    monkeypatch.setattr(checks, "read_text", lambda p: "up\n")
    assert checks.check_wireguard_interface(settings).status is Status.OK


def test_wireguard_down_is_warning(monkeypatch, settings):
    monkeypatch.setattr(checks, "path_exists", lambda p: True)
    monkeypatch.setattr(checks, "read_text", lambda p: "down\n")
    assert checks.check_wireguard_interface(settings).severity is Severity.WARNING


# --- software: edge model match correctness -------------------------------- #
def test_edge_model_malformed_json_is_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get", lambda u, **k: (200, "not json"))
    assert checks.check_edge_model(settings).is_critical_failure


def test_edge_model_rejects_different_family(monkeypatch, settings):
    body = '{"models":[{"name":"llama3.2-vision:11b"},{"name":"qwen2.5:3b"}]}'
    monkeypatch.setattr(checks, "http_get", lambda u, **k: (200, body))
    assert checks.check_edge_model(settings).is_critical_failure


def test_edge_model_accepts_family_tag(monkeypatch, settings):
    monkeypatch.setattr(checks, "http_get",
                        lambda u, **k: (200, '{"models":[{"name":"llama3.2:3b-instruct-q4"}]}'))
    assert checks.check_edge_model(settings).status is Status.OK


# --- hardware checks ------------------------------------------------------- #
def _usage(free_bytes):
    import collections
    return collections.namedtuple("U", "total used free")(100, 0, free_bytes)


def test_disk_space_low_is_warning(monkeypatch, settings):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _usage(10 * 1024 * 1024))
    assert checks.check_disk_space(settings).status is Status.WARN


def test_disk_space_ample_is_ok(monkeypatch, settings):
    monkeypatch.setattr(checks.shutil, "disk_usage", lambda p: _usage(5 * 1024 ** 3))
    assert checks.check_disk_space(settings).status is Status.OK


def test_voice_binaries_missing_is_warning_not_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "which", lambda b: False)
    r = checks.check_voice_binaries(settings)
    assert r.status is Status.WARN and r.severity is Severity.WARNING


def test_voice_binaries_present_is_ok(monkeypatch, settings):
    monkeypatch.setattr(checks, "which", lambda b: True)
    assert checks.check_voice_binaries(settings).status is Status.OK


def test_audio_output_missing_on_pi_is_critical(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "run", lambda cmd, **k: (127, "", ""))
    assert checks.check_audio_output(settings).is_critical_failure


def test_camera_absent_on_pi_is_warning(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks.glob, "glob", lambda p: [])
    assert checks.check_camera(settings).status is Status.WARN


@pytest.mark.parametrize("check", [checks.check_i2c_bus, checks.check_spi_bus])
def test_bus_absent_on_pi_is_warning_not_critical(monkeypatch, settings, check):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "path_exists", lambda p: False)
    r = check(settings)
    assert r.status is Status.WARN and not r.is_critical_failure


def test_thermal_hot_is_warning(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "read_text", lambda p: "85000\n")
    assert checks.check_thermal(settings).status is Status.WARN


def test_thermal_normal_is_ok(monkeypatch, settings):
    monkeypatch.setattr(checks, "is_pi", lambda: True)
    monkeypatch.setattr(checks, "read_text", lambda p: "50000\n")
    assert checks.check_thermal(settings).status is Status.OK
