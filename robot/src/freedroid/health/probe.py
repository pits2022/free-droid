"""Low-level probe helpers. Stdlib only, defensive — a probe never raises.

These wrap the OS so the individual checks stay declarative and testable: in unit
tests we monkeypatch these functions rather than the real system.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.parse
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


# ── EGY KÖRBEN EGY VÁRAKOZÁS (a Teremtő, 2026-09-08) ────────────────────────────
#
# Az STT (`:8080`) és az LLM (`:11434`) KÜLÖN próbálja a felhőt, ugyanazon a hoston. Ha
# az alagút halott, mindkettő ugyanazt a `probe_timeout_s`-t várja ki — mérve: körönként
# 2 x 0,5 s néma várakozás UGYANARRA a tényre.
#
# Miért NEM idő alapú gyorsítótár: a két próba egy körön belül 13 MÁSODPERCRE van
# egymástól (a köztes edge-átirat ideje, mérve a Pi-n), tehát a TTL-nek ennél hosszabbnak
# kellene lennie — az viszont már KÉT KÖRT is átfogna, és megsértené a modul kimondott
# invariánsát, hogy a háttérről KÉRÉSENKÉNT újra dönt (`test_kéresenkent_ujra_dont_a_
# hatterrol`: „egy »egyszer edge, mindig edge« kliens a felállt alagutat sosem venné
# észre"). A hatókör ezért a KÖR, nem az idő: az orchestrator minden kör elején törli.
#
# Csak a KAPCSOLÓDÁSI hibát jegyezzük (code == 0). Egy HTTP-hibakód azt BIZONYÍTJA, hogy
# a host felelt — abból a másik port halottságára következtetni hiba volna.
# SZÁLBIZTONSÁG: nincs zár, és ez feltétel, nem feledékenység. Mind a három hívó az
# orchestrator EGY körén belül fut (`_egy_kor` egyetlen `asyncio.to_thread`-ben), és a
# kör-hurok minden lépést AWAITOL, tehát a hívások szigorúan egymás után jönnek.
# ponytail: ha valaha `asyncio.gather`-rel párhuzamosítjuk az STT- és az LLM-próbát, ide
# `threading.Lock` kell — a versenyhelyzet ára egy kör, amiben a robot feleslegesen
# edge-re esik. (PR #117 review.)
_elerhetetlen_hostok: set[str] = set()


def _host(url: str) -> str:
    """Az URL gépneve. `hostname`, nem `netloc.split(":")` — mérve (PR #117 review):

        http://10.0.0.1:8080  -> '10.0.0.1'   '10.0.0.1'    (egyezik)
        http://[::1]:8080     -> '['          '::1'
        10.0.0.1:8080         -> ''           '10.0.0.1'

    A séma nélküli alak nem elméleti: az URL-ek env-ből felülírhatók
    (`FREEDROID_VOICE_STT_CLOUD_URL`). Az ÜRES host pedig rosszabb, mint a hibás: két
    KÜLÖNBÖZŐ gépen futó szolgáltatás is ugyanarra a kulcsra esne, azaz az egyik bukása
    a másikat is halottnak jelölné.
    """
    return urllib.parse.urlsplit(url if "//" in url else f"//{url}").hostname or ""


def uj_kor() -> None:
    """Új interakciós kör: a felhő-elérhetőségről mindent elfelejtünk."""
    _elerhetetlen_hostok.clear()


def korben_elerhetetlen(url: str) -> bool:
    """Megbukott-e MÁR EBBEN A KÖRBEN egy próba ugyanerre a hostra."""
    return _host(url) in _elerhetetlen_hostok


def jelold_elerhetetlennek(url: str) -> None:
    _elerhetetlen_hostok.add(_host(url))


def http_get(url: str, timeout: float = 4.0) -> tuple[int, str]:
    """HTTP GET; return (status_code, body). status_code=0 on connection error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local URL)
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, ""
