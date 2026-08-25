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
  * `--speak` esetén a KIMONDVA idő: ennyivel kell a generálásnak lépést tartania.

⚠️ **A script ALAPBÓL BEMELEGÍT** (`Orchestrator.start()`), mert a valódi robot is
melegen áll: a `warmup()` bootkor kifizeti a modell betöltését ÉS a rendszerprompt
prefilljét. E nélkül az első kérdés a Pi-n ~26 másodperccel többet mutat (mérve
2026-08-18: 6 s betöltés + 19,5 s a 654 tokenes rendszerprompt hideg prefillje) — az
a szám valós, de nem az üzemi állapoté. Hideg mérés: `--cold`.
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


def _naplozo_kamera():
    """Kameravezérlő helyett napló — ugyanaz az elv, mint a motoroknál: a tool-lánc
    végigmenjen, és LÁTSZÓDJON, mit hívott volna."""
    def naplo(nev):
        def hivas(*a):
            print(f"KAMERA: {nev} {' '.join(str(x) for x in a)}")
        return hivas
    return types.SimpleNamespace(pan=naplo("pan"), tilt=naplo("tilt"),
                                 action=naplo("action"), close=lambda: None)


def _alvo_watchdog():
    """Nem mérünk ultrahangot: a füstpróba a NYELVI láncról szól, és egy futó
    watchdog-szál a `fault`-jával feleslegesen tiltaná le a mozgás-tool-okat."""
    # `lambda: {}` és nem `dict`: a protokollban a `distances_cm` METÓDUS, tehát
    # hívhatónak kell lennie. (A #88 review itt egy sima `{}`-t javasolt — az
    # `TypeError`-t adna a `distances_cm()` híváskor; a `dict` működött, csak trükkös
    # volt olvasni.)
    return types.SimpleNamespace(fault=None, start=lambda: None,
                                 stop_monitoring=lambda: None,
                                 distances_cm=lambda: {}, is_blocked=lambda: False)


def _hallgat(vad, stt) -> str:
    """Egy kör a mikrofonból: felvétel a mondat végéig, majd átirat.

    A KÉT IDŐT KÜLÖN mérjük. A felvétel hossza a beszélőn múlik, az átiraté a gépen —
    összevonva nem lehetne megmondani, melyik a szűk keresztmetszet. MÉRVE 2026-08-25:
    a whisper `small` a Pi-n ~9-10 s, FÜGGETLENÜL a hang hosszától (a modell minden
    bemenetet 30 s-os ablakra tölt fel), tehát a második szám nagyjából állandó.
    """
    kezd = time.perf_counter()
    hang = vad.record_until_silence()
    felvetel_s = time.perf_counter() - kezd
    if not hang:
        # A puszta "nem hallottam" nem diagnózis: a MÉRT számok mondják meg, hogy a
        # küszöb volt magas, vagy tényleg csend volt.
        print(f"(nem hallottam semmit — zajszint {vad.zajszint:.0f}, "
              f"küszöb {vad.kuszob:.0f}; halkabb küszöb: FREEDROID_VOICE_VAD_SNR=2)")
        return ""
    kezd = time.perf_counter()
    szoveg = stt.transcribe(hang)
    print(f"HALLOTTAM: {szoveg!r}")
    print(f"   felvétel {felvetel_s:.1f} s ({len(hang) / 32000:.1f} s hang), "
          f"átirat {time.perf_counter() - kezd:.1f} s")
    return szoveg


def egy_kor(o, kerdes: str, tts=None) -> None:
    print(f"\n=== {kerdes}")
    kezd = time.perf_counter()
    valasz = o.ask(kerdes)
    telt = time.perf_counter() - kezd
    szavak = len(valasz.split())
    print(f"VÁLASZ: {valasz}")
    print(f"IDŐ:    {telt:.1f} s / {szavak} szó  (~{szavak / telt:.1f} szó/s)")
    print(f"INDOK:  {o.llm.decision()}")
    # A docstring eddig ígérte a FORRÁS sort, de senki nem írta ki — és e nélkül NEM
    # dönthető el, hogy a válasz a korpuszból jött-e vagy a fine-tune-ból. A demó-modell
    # kifejezetten "v12 + RAG", tehát ez a különbség a lényeg, nem részletkérdés.
    # Az `ask()` által ELTETT találatok, nem egy második lekérdezés: így a kiírt lista
    # akkor sem csúszhat el a valóságtól, ha a keresés egyszer megváltozik.
    talalatok = o.utolso_talalatok
    if talalatok:
        print("FORRÁS: " + ", ".join(f"{h.chunk.id}({h.score:.1f}) {h.chunk.title}"
                                     for h in talalatok))
    else:
        print("FORRÁS: — (nincs RAG-találat: a válasz a modellből jön)")
    if tts is not None:
        kezd = time.perf_counter()
        tts.speak(valasz)
        # A kimondás IDEJE külön szám: ez az, amivel a generálásnak lépést kell tartania
        # (a spec ~6,8 tok/s-os becslése épp ebből jött).
        print(f"KIMONDVA: {time.perf_counter() - kezd:.1f} s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kerdes", nargs="*", help="kérdés(ek); üresen a két alap-kérdés")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="folyamatos kérdezés (üres sor vagy Ctrl-D = kilépés)")
    ap.add_argument("--live-motion", action="store_true",
                    help="VALÓDI motorvezérlő — a robot MOZOGNI FOG. Polcold fel.")
    ap.add_argument("--cold", action="store_true",
                    help="NE melegítsen be — a hidegindítás árát méri (nem üzemi szám)")
    ap.add_argument("--listen", action="store_true",
                    help="MIKROFONBÓL kérdez (VAD + whisper.cpp) — a lánc HALLÓ eleje. "
                         "Ébresztőszó NINCS (openWakeWord blokkolt), tehát minden kör "
                         "ENTER-re indul: ez MÉRŐESZKÖZ, nem a demó kiváltója.")
    ap.add_argument("--speak", action="store_true",
                    help="mondja is KI a választ (Piper TTS) — a lánc HALLHATÓ vége")
    args = ap.parse_args()

    from freedroid.orchestrator import Orchestrator

    motion = None if args.live_motion else _naplozo_motor()
    if args.live_motion:
        print("⚠️  VALÓDI MOTORVEZÉRLŐ — a robot mozogni fog. 3 másodperced van.")
        time.sleep(3)

    # A KAMERA nem esik a `--live-motion` alá: a fejet mozgatni veszélytelen (a robot
    # nem hajt le az asztalról tőle), és e nélkül minden `camera` tool-hívás LookupError.
    # MÉRVE 2026-08-25: a modell "fordulj jobbra 90 fokot"-ra `camera pan right 90`-et
    # adott, és a füstpróba elhasalt rajta — a lánc jó volt, a vezérlő hiányzott.
    try:
        from freedroid.camera import PanTiltCamera
        camera = PanTiltCamera()
    except Exception as e:  # noqa: BLE001 — off-Pi ez a VÁRT eset, nem hiba
        print(f"kamera nélkül (naplózó): {type(e).__name__}: {e}")
        camera = _naplozo_kamera()

    tts = None
    if args.speak:
        from freedroid.voice import PiperTTS
        tts = PiperTTS()

    ful = None
    if args.listen:
        from freedroid.voice import EnergyVAD, WhisperCppSTT
        ful = (EnergyVAD(), WhisperCppSTT())

    o = Orchestrator(motion=motion, camera=camera, watchdog=_alvo_watchdog())
    if not args.cold:
        # Ugyanaz, amit a robot bootkor csinál: modell betöltése + a rendszerprompt
        # prefilljének cache-be melegítése. Enélkül a MÉRÉS a hidegindítást méri.
        kezd = time.perf_counter()
        hatter = o.llm.warmup()
        print(f"bemelegítés: {hatter.value if hatter else 'egyik háttér sem felelt'} "
              f"({time.perf_counter() - kezd:.1f} s)")
    try:
        # A `--listen` ugyanúgy kihagyja a beégetett kérdéseket, mint az `--interactive`:
        # aki a mikrofonhoz ült, nem a két alap-kérdésre kíváncsi (és az edge-ágon
        # kettő EGYENKÉNT fél perc, mire egyáltalán szóhoz jutna).
        sajat_kerdes = args.interactive or args.listen
        for kerdes in (args.kerdes or ([] if sajat_kerdes else ALAP_KERDESEK)):
            egy_kor(o, kerdes, tts)
        while ful is not None:
            try:
                input("\nENTER, és beszélj (Ctrl+D a kilépéshez)... ")
            except EOFError:
                break
            kerdes = _hallgat(*ful)
            if kerdes:
                egy_kor(o, kerdes, tts)
        while args.interactive:
            try:
                kerdes = input("\nkérdés> ").strip()
            except EOFError:
                break
            if not kerdes:
                break
            egy_kor(o, kerdes, tts)
    except KeyboardInterrupt:
        return 130
    finally:
        # Feltétel nélkül: a naplózó ál-motornak is van `close`-a, a watchdog-álnak is
        # `stop_monitoring`-ja, tehát ez mindkét módban biztonságos — és így az
        # orchestrátor bármely KÉSŐBBI erőforrása is lezárul, nem csak a motoré.
        o.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
