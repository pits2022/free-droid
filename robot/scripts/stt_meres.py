#!/usr/bin/env python3
"""Felhős (GPU) vs. edge (Pi) STT: UGYANAZ a hang, ugyanaz a kód-út.

    uv run python scripts/stt_meres.py

Miért nem elég a health-check: az csak azt mondja, hogy a szerver ÉL. Ez a különbség
2026-08-28-án nem elméleti volt — a `check_cloud_stt` (GET-próba) ZÖLDET adott egy olyan
whisper-serverre, amit az ELSŐ valódi POST `abort()`-tal ölt meg (PTX/toolchain, lásd az
`ai_stack` role `whisper_cuda_arch` változóját). A szolgáltatás életjele NEM bizonyíték.

Két bemenet, mert két KÜLÖNBÖZŐ kérdést mérnek:

  * **piper** — a referencia-mondatot a Piper mondja ki, tehát ISMERT a helyes szöveg.
    Tiszta jel: a MODELLT méri, nem a termet. ⚠️ Szintetikus hang: a termi jel-zaj
    viszonyról (a felismerés valódi szűk keresztmetszetéről) ez semmit nem mond.
  * **mikrofon** — valódi szobai felvétel: a realisztikus eset.

MÉRVE 2026-08-28 (H100 `ams3`, large-v3-turbo-q5_0 vs. Pi 5, small-q5_1):
felhő 0,31 s, edge 11,0 s — 35x, az alagúttal EGYÜTT. A szobai felvételre az edge
üres átiratot adott, a felhő szavakat: a nyereség nem csak sebesség.
"""

from __future__ import annotations

import pathlib
import subprocess
import time

from freedroid.config.settings import load_settings
from freedroid.voice import CloudWhisperSTT, WhisperCppSTT, find_voice_binary

REFERENCIA = "Szabi vagyok, a Teremtő szabad droidja, és a Yotengrit három nádszála vezet."
MIKROFON_WAV = "/home/creator/test-mic.wav"
KOROK = 3


def pcm(wav: str, rate: int) -> bytes:
    """Bármilyen WAV -> nyers 16 bites mono PCM — pontosan az az alak, amit a VAD ad.

    `sox`-szal, nem Pythonból: a 3.13 kidobta az `audioop`-ot, és egy kézzel írt
    átmintavételezés itt új hibaforrás lenne a MÉRŐESZKÖZBEN. A rossz ráta amúgy sem
    hibaüzenetet ad, hanem zagyva átiratot (mérve 2026-08-25).
    """
    return subprocess.run(
        ["sox", wav, "-t", "raw", "-r", str(rate), "-c", "1", "-b", "16",
         "-e", "signed-integer", "-"],
        capture_output=True, check=True).stdout


def piper_wav(cel: str, model: str) -> str:
    binaris = find_voice_binary("piper") or "piper"
    subprocess.run([binaris, "--model", model, "--output_file", cel],
                   input=REFERENCIA.encode(), capture_output=True, check=True)
    return cel


def meres(nev: str, stt, audio: bytes) -> None:
    print(f"\n--- {nev} ---")
    for i in range(1, KOROK + 1):
        t = time.perf_counter()
        try:
            szoveg = stt.transcribe(audio)
        except Exception as e:  # noqa: BLE001 — a hiba is mérési eredmény, nem megszakítás
            print(f"  {i}. HIBA  {time.perf_counter() - t:5.2f} s: {type(e).__name__}: {e}")
            continue
        print(f"  {i}. {time.perf_counter() - t:5.2f} s  {szoveg!r}")


def main() -> None:
    cfg = load_settings()
    rate = cfg.voice.stt_sample_rate
    model = str(pathlib.Path(cfg.voice.piper_model).expanduser())

    felho, edge = CloudWhisperSTT(cfg), WhisperCppSTT(cfg)
    print(f"felhő: {cfg.voice.stt_cloud_url} -> {felho.elerheto()[1]}")
    print(f"edge : {cfg.voice.whisper_model}")
    print(f"referencia: {REFERENCIA!r}")

    forrasok = {
        "piper (ismert szöveg, TISZTA jel — a modellt méri, nem a termet)":
            piper_wav("/tmp/stt_ref.wav", model),
        "mikrofon (valódi szobai felvétel)": MIKROFON_WAV,
    }
    for cimke, wav in forrasok.items():
        if not pathlib.Path(wav).exists():
            print(f"\n(kihagyva: {wav} nincs meg)")
            continue
        audio = pcm(wav, rate)
        print(f"\n{'=' * 70}\n{cimke}  ({len(audio) / 2 / rate:.1f} s hang)\n{'=' * 70}")
        meres("FELHŐ (GPU, large-v3-turbo)", felho, audio)
        meres("EDGE (Pi 5, small-q5_1)", edge, audio)


if __name__ == "__main__":
    main()
