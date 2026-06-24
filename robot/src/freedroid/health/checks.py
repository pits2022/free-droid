"""Individual vital-function checks, grouped by layer.

Each check is ``(settings) -> CheckResult`` and never raises. Hardware checks
return SKIPPED off-Pi so the same suite runs cleanly on a dev laptop.

Severity reflects the architecture:
  - The CLOUD is on-demand/disposable -> cloud-dependent checks are WARNING
    (edge fallback covers them); their failure is expected when the cloud is down.
  - The EDGE inference stack, the safety-relevant hardware, and the local control
    process are vital -> CRITICAL.
"""

from __future__ import annotations

import glob
import json
import shutil
from typing import TYPE_CHECKING, Callable

from freedroid.health.model import (
    CheckResult,
    Layer,
    Severity,
    fail,
    ok,
    skipped,
    warn,
)
from freedroid.health.probe import http_get, is_pi, path_exists, read_text, run, which

if TYPE_CHECKING:
    from freedroid.config.settings import Settings

Check = Callable[["Settings"], CheckResult]

# systemd unit names (override per deployment if needed).
SERVICE_WIREGUARD = "wg-quick@wg0"
SERVICE_OLLAMA = "ollama"
SERVICE_ORCHESTRATOR = "freedroid"

THERMAL_WARN_C = 80.0
DISK_FREE_WARN_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB


# --------------------------------------------------------------------------- #
# Network layer (cloud-dependent -> WARNING; edge fallback covers an outage)
# --------------------------------------------------------------------------- #
def check_wireguard_interface(settings: Settings) -> CheckResult:
    name = "wireguard_interface"
    if not path_exists("/sys/class/net/wg0"):
        return fail(name, Layer.NETWORK, Severity.WARNING, "wg0 interface absent",
                    remediation="restart_wireguard")
    raw = read_text("/sys/class/net/wg0/operstate")
    if raw is None:
        return warn(name, Layer.NETWORK, "cannot read wg0 operstate")
    state = raw.strip()
    if state in ("up", "unknown"):  # wg interfaces often report 'unknown'
        return ok(name, Layer.NETWORK, detail="wg0 up")
    return fail(name, Layer.NETWORK, Severity.WARNING, f"wg0 state={state}",
                remediation="restart_wireguard")


def check_cloud_ollama(settings: Settings) -> CheckResult:
    name = "cloud_ollama"
    code, _ = http_get(f"{settings.llm.cloud_url}/api/tags")
    if code == 200:
        return ok(name, Layer.NETWORK, detail="cloud Ollama reachable")
    # Expected when the on-demand cloud server is destroyed -> WARN, not FAIL.
    return warn(name, Layer.NETWORK, "cloud Ollama unreachable — using edge fallback")


# --------------------------------------------------------------------------- #
# Hardware layer (Pi-only; SKIPPED off-Pi)
# --------------------------------------------------------------------------- #
def check_gpio_chip(settings: Settings) -> CheckResult:
    name = "gpio_chip"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    if glob.glob("/dev/gpiochip*"):
        return ok(name, Layer.HARDWARE, severity=Severity.CRITICAL, detail="gpiochip present")
    return fail(name, Layer.HARDWARE, Severity.CRITICAL, "no /dev/gpiochip* (motors+ultrasonic)")


def check_i2c_bus(settings: Settings) -> CheckResult:
    name = "i2c_bus"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    if path_exists("/dev/i2c-1"):
        return ok(name, Layer.HARDWARE, detail="i2c-1 present (PCA9685)")
    return warn(name, Layer.HARDWARE, "/dev/i2c-1 absent — camera pan/tilt unavailable")


def check_spi_bus(settings: Settings) -> CheckResult:
    name = "spi_bus"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    if path_exists("/dev/spidev0.0"):
        return ok(name, Layer.HARDWARE, detail="spidev0.0 present (WS2812)")
    return warn(name, Layer.HARDWARE, "/dev/spidev0.0 absent — status LED unavailable")


def check_audio_input(settings: Settings) -> CheckResult:
    name = "audio_input"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    rc, out, _ = run(["arecord", "-l"])
    if rc == 0 and "card" in out:
        return ok(name, Layer.HARDWARE, severity=Severity.CRITICAL, detail="capture device present")
    return fail(name, Layer.HARDWARE, Severity.CRITICAL, "no audio capture device (mic)")


def check_audio_output(settings: Settings) -> CheckResult:
    name = "audio_output"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    rc, out, _ = run(["aplay", "-l"])
    if rc == 0 and "card" in out:
        return ok(name, Layer.HARDWARE, severity=Severity.CRITICAL, detail="playback device present")
    return fail(name, Layer.HARDWARE, Severity.CRITICAL, "no audio playback device (speaker)")


def check_camera(settings: Settings) -> CheckResult:
    name = "camera"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    if glob.glob("/dev/video*"):
        return ok(name, Layer.HARDWARE, detail="video device present")
    return warn(name, Layer.HARDWARE, "no /dev/video* — camera unavailable")


def check_thermal(settings: Settings) -> CheckResult:
    name = "thermal"
    if not is_pi():
        return skipped(name, Layer.HARDWARE, "not on a Raspberry Pi")
    raw = read_text("/sys/class/thermal/thermal_zone0/temp")
    if raw is None:
        return warn(name, Layer.HARDWARE, "cannot read temperature")
    try:
        temp_c = int(raw.strip()) / 1000.0
    except ValueError:
        return warn(name, Layer.HARDWARE, "unparseable temperature")
    if temp_c >= THERMAL_WARN_C:
        return warn(name, Layer.HARDWARE, f"CPU hot: {temp_c:.0f}°C")
    return ok(name, Layer.HARDWARE, detail=f"CPU {temp_c:.0f}°C")


def check_disk_space(settings: Settings) -> CheckResult:
    name = "disk_space"
    try:
        free = shutil.disk_usage("/").free
    except OSError as e:
        return warn(name, Layer.HARDWARE, f"cannot stat /: {e}")
    if free < DISK_FREE_WARN_BYTES:
        return warn(name, Layer.HARDWARE, f"low disk: {free // (1024 * 1024)} MiB free")
    return ok(name, Layer.HARDWARE, detail=f"{free // (1024 * 1024)} MiB free")


# --------------------------------------------------------------------------- #
# Software layer (edge brain + control process are vital -> CRITICAL)
# --------------------------------------------------------------------------- #
def check_edge_ollama(settings: Settings) -> CheckResult:
    name = "edge_ollama"
    code, _ = http_get(f"{settings.llm.edge_url}/api/tags")
    if code == 200:
        return ok(name, Layer.SOFTWARE, severity=Severity.CRITICAL, detail="edge Ollama up")
    return fail(name, Layer.SOFTWARE, Severity.CRITICAL,
                "edge Ollama unreachable (offline brain)", remediation="restart_ollama")


def check_edge_model(settings: Settings) -> CheckResult:
    name = "edge_model"
    code, body = http_get(f"{settings.llm.edge_url}/api/tags")
    if code != 200:
        return skipped(name, Layer.SOFTWARE, "edge Ollama unreachable (see edge_ollama)")
    try:
        names = [m.get("name", "") for m in json.loads(body).get("models", [])]
    except (ValueError, AttributeError):
        # Can't confirm the offline brain's model is loaded — same safety meaning
        # as "model absent", so CRITICAL, not a downgraded WARNING.
        return fail(name, Layer.SOFTWARE, Severity.CRITICAL,
                    "cannot parse Ollama /api/tags")
    wanted = settings.llm.model
    base = wanted.split(":")[0]
    if any(n == wanted or n.startswith(base + ":") for n in names):
        return ok(name, Layer.SOFTWARE, severity=Severity.CRITICAL, detail=f"{wanted} loaded")
    return fail(name, Layer.SOFTWARE, Severity.CRITICAL,
                f"model {wanted} not in Ollama ({names})")


def check_orchestrator_service(settings: Settings) -> CheckResult:
    name = "orchestrator_service"
    if not is_pi():
        return skipped(name, Layer.SOFTWARE, "not on a Raspberry Pi")
    rc, out, _ = run(["systemctl", "is-active", SERVICE_ORCHESTRATOR])
    if rc == 0 and out.strip() == "active":
        return ok(name, Layer.SOFTWARE, severity=Severity.CRITICAL, detail="orchestrator active")
    return fail(name, Layer.SOFTWARE, Severity.CRITICAL,
                f"{SERVICE_ORCHESTRATOR} not active ({out.strip() or 'unknown'})",
                remediation="restart_orchestrator")


def check_voice_binaries(settings: Settings) -> CheckResult:
    name = "voice_binaries"
    missing = [b for b in ("piper", "whisper-cli") if not which(b)]
    if not missing:
        return ok(name, Layer.SOFTWARE, detail="voice binaries present")
    # Phase 4.2 not installed yet -> WARNING, not a vital failure.
    return warn(name, Layer.SOFTWARE, f"voice binaries missing: {', '.join(missing)}")


def check_package_import(settings: Settings) -> CheckResult:
    name = "package_import"
    try:
        import freedroid  # noqa: F401
    except Exception as e:  # pragma: no cover - the test env always has it
        return fail(name, Layer.SOFTWARE, Severity.CRITICAL, f"freedroid import failed: {e}")
    return ok(name, Layer.SOFTWARE, severity=Severity.CRITICAL, detail="package importable")


# Ordered registry — network, then hardware, then software.
ALL_CHECKS: tuple[Check, ...] = (
    check_wireguard_interface,
    check_cloud_ollama,
    check_gpio_chip,
    check_i2c_bus,
    check_spi_bus,
    check_audio_input,
    check_audio_output,
    check_camera,
    check_thermal,
    check_disk_space,
    check_edge_ollama,
    check_edge_model,
    check_orchestrator_service,
    check_voice_binaries,
    check_package_import,
)
