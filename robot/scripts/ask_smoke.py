#!/usr/bin/env python3
"""A teljes lánc füstpróbája HANG NÉLKÜL — kérdés -> RAG -> LLM -> nyelvi őr -> tool-ok.

Ez az a teszt, ami a `voice/` elkészülte ELŐTT is végigméri a robotot, és ami után
a `run()` hurok már csak a mikrofont teszi hozzá. Billentyűzetről, a Pi-n.

    uv run python scripts/ask_smoke.py                  # a két alap-kérdés
    uv run python scripts/ask_smoke.py "Mi az a Büün?"  # saját kérdés(ek)
    uv run python scripts/ask_smoke.py -i               # interaktív

**A MOTOROK ALAPBÓL NEM MOZOGNAK.** A `<tool>move…</tool>` hívások csak kiíródnak
(`MOTOR: move …`). Ez nem kényelmi döntés: a füstpróba jellemzően SSH-ból fut, egy
asztalon álló robot pedig lehajt róla. Valódi mozgáshoz `--live-motion` kell, és
akkor is a felpolcolt robot a helyes elrendezés.

Amit érdemes leolvasni belőle:
  * `INDOK` — MELYIK háttér felelt és MIÉRT (a felhő halott volt, vagy hibázott?).
  * `FORRÁS` — talált-e a RAG chunkot; üres lista tény-kérdésnél a keresés hibája.
  * `MOTOR:` — a tool-lánc végigment-e a parsertől a vezérlőig.
  * a másodperc — a 3B tok/s-a a Pi-n a hang-pipeline költségvetésének a fele.
"""

from __future__ import annotations

import argparse
import time
import types

ALAP_KERDESEK = [
    "Mi az a Yotengrit?",   # RAG-nak találnia kell
    "Szabi, gyere ide!",    # tool-hívást kell adnia
]


def _naplozo_motor():
    """Motorvezérlő helyett napló. A `heading`/`is_turning` azért kell, mert a
    watchdog ezeket olvasná — itt csak a felület teljessége miatt."""
    return types.SimpleNamespace(
        heading=None, is_turning=False,
        stop=lambda: print("MOTOR: stop"),
        move=lambda **kw: print(f"MOTOR: move {kw}"),
        turn=lambda **kw: print(f"MOTOR: turn {kw}"),
        set_speed=lambda s: print(f"MOTOR: set_speed {s}"),
        close=lambda: None,
    )


def _alvo_watchdog():
    """Nem mérünk ultrahangot: a füstpróba a NYELVI láncról szól, és egy futó
    watchdog-szál a `fault`-jával feleslegesen tiltaná le a mozgás-tool-okat."""
    return types.SimpleNamespace(fault=None, start=lambda: None,
                                 stop_monitoring=lambda: None,
                                 distances_cm=dict, is_blocked=lambda: False)


def egy_kor(o, kerdes: str) -> None:
    print(f"\n=== {kerdes}")
    kezd = time.perf_counter()
    valasz = o.ask(kerdes)
    telt = time.perf_counter() - kezd
    szavak = len(valasz.split())
    print(f"VÁLASZ: {valasz}")
    print(f"IDŐ:    {telt:.1f} s / {szavak} szó  (~{szavak / telt:.1f} szó/s)")
    print(f"INDOK:  {o.llm.decision()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kerdes", nargs="*", help="kérdés(ek); üresen a két alap-kérdés")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="folyamatos kérdezés (üres sor vagy Ctrl-D = kilépés)")
    ap.add_argument("--live-motion", action="store_true",
                    help="VALÓDI motorvezérlő — a robot MOZOGNI FOG. Polcold fel.")
    args = ap.parse_args()

    from freedroid.orchestrator import Orchestrator

    motion = None if args.live_motion else _naplozo_motor()
    if args.live_motion:
        print("⚠️  VALÓDI MOTORVEZÉRLŐ — a robot mozogni fog. 3 másodperced van.")
        time.sleep(3)

    o = Orchestrator(motion=motion, watchdog=_alvo_watchdog())
    try:
        for kerdes in (args.kerdes or ([] if args.interactive else ALAP_KERDESEK)):
            egy_kor(o, kerdes)
        while args.interactive:
            try:
                kerdes = input("\nkérdés> ").strip()
            except EOFError:
                break
            if not kerdes:
                break
            egy_kor(o, kerdes)
    except KeyboardInterrupt:
        return 130
    finally:
        # Csak a valódi vezérlőt kell lezárni; a naplózó álnak nincs mit.
        if args.live_motion:
            o.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
