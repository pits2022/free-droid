"""Low-level probe helpers. Stdlib only, defensive — a probe never raises.

These wrap the OS so the individual checks stay declarative and testable: in unit
tests we monkeypatch these functions rather than the real system.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.request


def is_pi() -> bool:
    """True on a Raspberry Pi (used to SKIP hardware checks elsewhere).

    Multi-signal so a single unreadable sysfs file doesn't misreport a real Pi as
    "not a Pi" (which would silently SKIP the CRITICAL hardware checks). On the
    robot, set FREEDROID_ASSUME_PI=1 to force-enable hardware checks regardless —
    then a missing device FAILs (fail-safe) instead of being skipped.
    """
    if os.environ.get("FREEDROID_ASSUME_PI") == "1":
        return True
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as fh:
                if b"Raspberry Pi" in fh.read():
                    return True
        except OSError:
            continue
    try:
        with open("/proc/cpuinfo") as fh:
            text = fh.read()
        if "Raspberry Pi" in text or "BCM2" in text:
            return True
    except OSError:
        pass
    return False


def path_exists(path: str) -> bool:
    return os.path.exists(path)


def read_text(path: str) -> str | None:
    """Read a small sysfs/proc file. Returns None if unreadable (never raises)."""
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def which(binary: str) -> bool:
    return shutil.which(binary) is not None


def run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a command; return (rc, stdout, stderr). rc=127 if the binary is missing,
    rc=124 on timeout. Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"
    except OSError as e:  # pragma: no cover - defensive
        return 1, "", str(e)


def http_get(url: str, timeout: float = 4.0) -> tuple[int, str]:
    """HTTP GET; return (status_code, body). status_code=0 on connection error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local URL)
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, ""
