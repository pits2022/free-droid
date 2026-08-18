"""`freedroid-health` entry point.

Run at boot and on a timer (systemd). Flow: run checks → self-heal fixable
failures → re-check → write a JSON status file + log to journald → set safe-mode
(or clear it) → exit 0 if vital functions are healthy, 1 otherwise, 2 if the
safe-mode flag itself could not be written.

**A szolgáltatás ROOTKÉNT fut** (`freedroid-health.service`): `systemctl restart`-ot
ad ki önjavításkor, és a `/run/freedroid/` alá ír. Kézzel, `creator`-ként indítva a
`/run/freedroid` root tulajdonú, tehát az írások jogosultsághibára futnak — ez nem
elromlott gép, hanem hiányzó `sudo`. Az üzenetek ezt ki is mondják.
"""

from __future__ import annotations

import os
import sys
import time

from freedroid.config.settings import load_settings
from freedroid.health.model import HealthReport, Status
from freedroid.health.runner import heal_and_recheck
from freedroid.health.safemode import clear_safe_mode, enter_safe_mode, write_durably

STATUS_PATH = os.environ.get("FREEDROID_HEALTH_STATUS", "/run/freedroid/health.json")


def write_status(report: HealthReport, path: str | None = None) -> None:
    """Az állapot kiírása — ATOMIAN, mint a safe-mode jelző.

    Két baja volt a sima `open(path, "w")`-nek, és a második az, ami a Pi-n elő is jött:
      1. egy félbeszakadt írás CSONKA JSON-t hagy, amit az olvasó (Phase-4 orchestrátor,
         monitorozás) érvényes fájlnak lát — a csere ezt szerkezetileg kizárja;
      2. ha az előző példányt a ROOTKÉNT futó systemd-szolgáltatás írta, egy kézi,
         `creator`-ként indított futás nem tudta felülírni. Az `os.replace` viszont a
         KÖNYVTÁRRA kér jogot, nem a fájlra — így ugyanaz a kód mindkét gazdának jó.

    A hiba itt továbbra is csak figyelmeztetés: az állapotfájl TÁJÉKOZTATÓ. A safe-mode
    jelző az, ami szerződés, és az hangosan bukik (lásd `main`).
    """
    path = path or STATUS_PATH
    try:
        write_durably(path, report.to_json())
    except OSError as e:  # pragma: no cover - defensive
        print(f"health: cannot write status {path}: {e}", file=sys.stderr)


def log_report(report: HealthReport) -> None:
    print(f"health: {report.summary()}", file=sys.stderr)
    for r in report.results:
        if r.status is not Status.OK:
            print(f"health:   [{r.status.value}] {r.layer.value}/{r.name}: {r.detail}",
                  file=sys.stderr)
    if report.remediated:
        print(f"health: remediated: {', '.join(report.remediated)}", file=sys.stderr)


def _sudo_tipp(e: OSError) -> None:
    """A leggyakoribb ok kézi futtatásnál — és nem hiba a gépben."""
    if isinstance(e, PermissionError) and os.geteuid() != 0:
        print("health:   -> nem rootként futsz; a szolgáltatás rootként fut "
              "(sudo -E, vagy `systemctl start freedroid-health`).", file=sys.stderr)


def main() -> int:
    settings = load_settings()
    report = heal_and_recheck(settings, time.time())
    write_status(report)
    log_report(report)
    # A safe-mode jelzőnek MINDKÉT irányban tükröznie kell a valóságot, és mindkét
    # irányban ugyanaz a tét: ha nem sikerül, az orchestrátor rossz állapotot lát.
    if report.healthy:
        try:
            clear_safe_mode()
        except OSError as e:
            print(f"health: A SAFE MODE JELZŐ NEM TÖRÖLHETŐ: {e}", file=sys.stderr)
            print("health:   -> az életfunkciók RENDBEN vannak, de a bent ragadt jelző "
                  "miatt az orchestrátor safe mode-ban marad (nem fog mozogni).",
                  file=sys.stderr)
            _sudo_tipp(e)
            return 2
        return report.exit_code()

    # A `safemode` modul SZÁNDÉKOSAN dob, ha a jelzőt nem tudja kiírni ("a caller must
    # surface that as a hard failure, never continue as if safe-mode is in effect") —
    # csakhogy eddig senki nem teljesítette ezt a szerződést: a kivétel nyers
    # tracebackként szállt ki. Két baja volt, és a második a súlyosabb:
    #   1. a 10 percenként futó timer minden körben tracebacket írt a journalba, ami
    #      pont arra tanítja az embert, hogy ne olvassa;
    #   2. az EGYETLEN mondat, ami számít — hogy a safe mode NEM lett rögzítve, tehát
    #      az orchestrátor nem fogja látni —, sehol nem hangzott el. A traceback egy
    #      tmp fájl jogosultságáról beszélt.
    try:
        enter_safe_mode(report)
    except OSError as e:
        print(f"health: A SAFE MODE JELZŐ NEM ÍRHATÓ: {e}", file=sys.stderr)
        print("health:   -> az orchestrátor NEM fogja látni a safe mode-ot, "
              "a mozgás NEM lesz letiltva.", file=sys.stderr)
        _sudo_tipp(e)
        return 2
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
