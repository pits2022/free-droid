#!/usr/bin/env python3
"""Phase 1.5 smoke test — is the USB LTE modem up and is there net on the SIM?

A Huawei E3372 in HiLink mode appears as a virtual ethernet NIC (usb0 / eth1 /
enx…) that DHCPs automatically. This lists candidate interfaces and checks
connectivity. Run on the Pi:  uv run python scripts/lte_modem_test.py
"""

from __future__ import annotations

import shutil
import subprocess


def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str]:
    if shutil.which(cmd[0]) is None:
        return 127, f"(missing: {cmd[0]})"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (subprocess.SubprocessError, OSError) as e:
        return 1, f"(error: {e})"


def main() -> int:
    print("== network interfaces ==")
    _, links = _run(["ip", "-br", "addr"])
    print(links)
    candidates = [ln.split()[0] for ln in links.splitlines()
                  if ln[:4] in ("usb0", "eth1") or ln.startswith("enx")]
    print(f"\nlikely HiLink modem interface(s): {candidates or '(none found)'}")

    print("\n== HiLink web UI (192.168.8.1) ==")
    rc, _ = _run(["ping", "-c", "1", "-W", "2", "192.168.8.1"])
    print("reachable" if rc == 0 else "not reachable (modem may use a different IP)")

    print("\n== internet via the SIM (ping 1.1.1.1) ==")
    rc, out = _run(["ping", "-c", "2", "-W", "3", "1.1.1.1"])
    print(out)
    print("RESULT:", "ONLINE" if rc == 0 else "NO INTERNET")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
