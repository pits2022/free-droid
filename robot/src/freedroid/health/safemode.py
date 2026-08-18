"""Safe-mode flag — the fallback when self-healing didn't restore a vital function.

Writes a flag file that the orchestrator (Phase 4) reads to disable motion and use
canned replies. Driving the WS2812 error colour is a Phase-4 hook (LED controller
not implemented yet).

The flag is the safety contract, so writing it is NOT best-effort: the write is
atomic + fsynced, and a failure is raised loudly rather than swallowed (a swallowed
write failure would mean "reported safe-mode but motion still enabled"). The Phase-4
orchestrator must also fail safe if the status/flag is missing or stale.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freedroid.health.model import HealthReport

SAFE_MODE_FLAG = os.environ.get("FREEDROID_SAFE_MODE_FLAG", "/run/freedroid/safe_mode")


def write_durably(path: str, content: str) -> None:
    """Atomic, fsynced write. Raises OSError on failure (intentionally not swallowed).

    Nyilvános, mert a `cli.write_status` is ezt használja, és a KÖZÖS rész nem a
    tartósság, hanem a CSERE: az `os.replace` a KÖNYVTÁRRA kér írásjogot, nem a
    meglévő fájlra. Ezért működik akkor is, ha az előző példányt a rootként futó
    systemd-szolgáltatás írta, és most `creator`-ként futunk kézzel — egy sima
    `open(path, "w")` ott jogosultsághibára futna.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # `mkstemp` és nem `f"{path}.tmp.{os.getpid()}"` (PR #89/#88 review). A PID-es név
    # két külön hívónál ütközhet — a folyamat MINDEN szála ugyanazt a PID-et látja —,
    # és felül is írna egy ott felejtett fájlt.
    #
    # Miért nem elég egy `O_EXCL` a régi néven: azzal egy OTT FELEJTETT tmp (összeomlás
    # + PID-újrafelhasználás) minden későbbi írást MEGBUKTATNA. Egy biztonsági jelzőnél
    # a tartós írásképtelenség rosszabb, mint a felülírás. A `mkstemp` egyedi nevet ad,
    # tehát egyik hibamód sem áll fenn.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".tmp.")
    try:
        try:
            os.fchmod(fd, 0o644)   # a mkstemp 0600-at ad; ezt más is olvashatja
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        # A CSERE is a takarító ágon belül: ha ez bukik (csak olvasható fájlrendszer,
        # kvóta), a tmp itt maradna — és a 10 percenként futó időzítő minden körben
        # hagyna egyet a /run-ban. (PR #88/#89 review.)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)   # ne hagyjunk szemetet; a takarítás hibája ne nyelje el az igazit
        raise
    # A könyvtár-bejegyzés tartóssá tétele. Ez SZÁNDÉKOSAN a takarító ágon KÍVÜL van:
    # a sikeres `os.replace` után a tmp már nem létezik (átnevezés), tehát innentől
    # nincs mit szivárogtatni — a review ezt a részt tévesen sorolta ide.
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def enter_safe_mode(report: HealthReport, flag_path: str | None = None) -> None:
    """Record safe-mode with the failing vital functions.

    Logs first (so the reason is always visible), then writes the flag durably.
    Raises if the flag cannot be written — the caller must surface that as a hard
    failure, never continue as if safe-mode is in effect.
    """
    flag_path = flag_path or SAFE_MODE_FLAG
    reasons = "\n".join(f"{r.name}: {r.detail}" for r in report.critical_failures())
    print("health: ENTERING SAFE MODE — vital functions down:", file=sys.stderr)
    for line in reasons.splitlines():
        print(f"health:   {line}", file=sys.stderr)
    write_durably(flag_path, reasons + "\n")
    # TODO(Phase 4): drive the WS2812 ring to the error state here.


def clear_safe_mode(flag_path: str | None = None) -> None:
    """A safe-mode jelző törlése, ha az életfunkciók helyreálltak.

    A testvérével (`enter_safe_mode`) AZONOS szerződés: hiba esetén DOB, és a hívó
    dolga felszínre hozni. Korábban itt csak egy figyelmeztetés ment a stderr-re, a
    `main` pedig 0-val (= egészséges) tért vissza — miközben a bent ragadt jelző miatt
    az orchestrátor SAFE MODE-ban marad, azaz nem mozog. A kilépési kód tehát hazudott,
    és pont az ellenkezőjét állította a valóságnak. (PR #89 review nyomán; a bejelentett
    "őrizetlen kivétel" nem állt fenn — a valódi hiba a kilépési kód volt.)

    A hiányzó fájl NEM hiba: a jelző törlése idempotens.
    """
    flag_path = flag_path or SAFE_MODE_FLAG
    try:
        os.remove(flag_path)
    except FileNotFoundError:
        pass
