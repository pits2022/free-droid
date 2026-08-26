#!/usr/bin/env python3
"""Bring-up önteszt — AKTÍV ellenőrzés, operátor jelenlétében, indulás előtt.

MI EZ, ÉS MI NEM. A `freedroid-health` FELÜGYELET NÉLKÜL fut, 10 percenként,
tehát csak ESZKÖZ-JELENLÉTET nézhet: `arecord -l`, `/dev/video*`, `gpiochip`. Sosem
szólal meg, nem vesz fel képet, nem mér távolságot és nem mozdít semmit — helyesen, mert
egy magától induló ellenőrzés nem mozgathatja a robotot.

Ez a script a MÁSIK fél: megszólal, felvesz, mér és mozgat. A passzív réteget NEM írja
újra, hanem MEGHÍVJA (`run_checks`), és a saját aktív méréseit ugyanabba a `CheckResult`
modellbe teszi — így egy verdikt és egy kilépési kód lesz a végén, a demó napján
indulás előtti ellenőrzésnek.

    uv run python scripts/self_check.py                 # minden, a lánctalpak NÉLKÜL
    uv run python scripts/self_check.py --live-motion   # + a lánctalpak (a robot MOZOG)
    uv run python scripts/self_check.py --json          # gépi kimenet

AMIT SZÁNDÉKOSAN NEM TUD. A szervó-ellenőrzés azt méri, hogy a parancs hiba nélkül
kimegy — hogy a kamera TÉNYLEGESEN elfordult-e, ahhoz látás kellene. A kamera-KÉP
viszont valódi képkockát néz, és nem a fájlméretet: egy letakart vagy leszakadt kamera
jellemzően EGYENLETES képet ad, tehát a szórás a lelet.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import statistics
import subprocess
import time

from freedroid.config import gpio as G
from freedroid.config.settings import Settings, load_settings
from freedroid.health.model import (
    CheckResult,
    HealthReport,
    Layer,
    Severity,
    Status,
    fail,
    ok,
    warn,
)
from freedroid.health.probe import run
from freedroid.health.runner import run_checks

# A hurok-teszt hangja. 1 kHz: a hangszóró és a mikrofon sávjának közepe, és bőven a
# 16 kHz-es mintavétel Nyquist-határa alatt — nem a mérés fizikája miatt választott
# szám, hanem hogy semmiféle szűrő ne magyarázhassa el a hiányát.
TONE_HZ = 1000.0
TONE_S = 1.0
# A csúcs/medián arány a spektrumban. MÉRVE 2026-08-26 a roboton: működő hurokra
# **12603**, tehát a küszöb nem hajszálon áll — a hiányzó hang egy-két nagyságrenddel
# lentebb landol. A szám a `részlet`-ben mindig megjelenik: ha egyszer a küszöb közelébe
# csúszik, az a hardver romlása, nem a küszöb rossz megválasztása.
TONE_MIN_ARANY = 50.0
# Ez alatt a kép EGYENLETES: letakart lencse, leszakadt kábel, vagy fekete képkocka.
KEP_MIN_SZORAS = 5.0
# A felvétel olvasásának FELSŐ HATÁRA. Ugyanaz az elv, mint a `speak_timeout_s`-nél: egy
# beragadt hangeszköz mellett az `arecord` ÉL, csak nem ad mintát — a `read(n)` ilyenkor
# örökre blokkol, és a takarítás (`finally`) sem fut le. Egy hangos hiba mindig jobb, mint
# egy néma megállás. (PR #96 review.)
FELVETEL_HATARIDO_S = 5.0


def _cr(nev: str, layer: Layer, rendben: bool, reszlet: str,
        severity: Severity = Severity.WARNING) -> CheckResult:
    return (ok(nev, layer, severity, reszlet) if rendben
            else fail(nev, layer, severity, reszlet))


# --- óra, memória, safe mode -------------------------------------------------

def check_ora(_: Settings) -> CheckResult:
    """A Pi-ben NINCS RTC. Hibás órával a TLS és a WireGuard-kézfogás is elhasalhat —
    hidegindítás után, a helyszínen, ahol a hálózat úgyis a gyanúsított lenne."""
    kod, ki, _hiba = run(["timedatectl", "show", "-p", "NTPSynchronized",
                          "-p", "TimeUSec", "--value"])
    if kod != 0:
        return warn("clock", Layer.SOFTWARE, "timedatectl nem futott")
    sorok = ki.split()
    szinkron = bool(sorok) and sorok[0] == "yes"
    most = time.strftime("%Y-%m-%d %H:%M:%S")
    return _cr("clock", Layer.SOFTWARE, szinkron,
               f"{most}, NTP szinkron: {'igen' if szinkron else 'NEM'}")


def check_memoria(_: Settings) -> CheckResult:
    with open("/proc/meminfo") as f:
        mezok = dict(sor.split(":", 1) for sor in f)
    szabad_mb = int(mezok["MemAvailable"].split()[0]) / 1024
    # A 3B modell ~2 GB-ot kér. Egy megtelt gépen az Ollama nem hibaüzenetet ad, hanem
    # lassan swappel — a demón ez "a robot gondolkodik" képében jelenik meg.
    return _cr("memory", Layer.SOFTWARE, szabad_mb >= 2048, f"{szabad_mb:.0f} MB szabad")


def check_safe_mode(_: Settings) -> CheckResult:
    from freedroid.health.safemode import SAFE_MODE_FLAG

    try:
        with open(SAFE_MODE_FLAG) as f:
            tartalom = f.read().strip().splitlines()
    except FileNotFoundError:
        return ok("safe_mode", Layer.SOFTWARE, Severity.WARNING, "nincs jelző — szabad")
    return warn("safe_mode", Layer.SOFTWARE,
                f"BE VAN KAPCSOLVA: {'; '.join(tartalom[:3]) or SAFE_MODE_FLAG}")


# --- ultrahang ---------------------------------------------------------------

def check_ultrahang(settings: Settings, korok: int) -> list[CheckResult]:
    """N teljes watchdog-kör, szenzoronként medián + szórás + a néma mérések aránya.

    A VALÓDI watchdogot futtatja (`poll_once`), nem egy másolatot a mérőciklusból: egy
    újraírt mérés a saját hibáit mérné. Az `on_obstacle` itt szándékosan no-op — a
    motorokat ez a lépés nem indítja el, tehát megállítania sincs mit.
    """
    from freedroid.safety import UltrasonicWatchdog

    wd = UltrasonicWatchdog(on_obstacle=lambda: None, settings=settings)
    minta: dict[str, list[float | None]] = {n: [] for n in G.ULTRASONIC}
    try:
        for _ in range(korok):
            wd.poll_once()
            for nev, cm in wd.distances_cm().items():
                minta[nev].append(cm)
    finally:
        wd.close()

    eredmeny = []
    for nev, ertekek in minta.items():
        szamok = [v for v in ertekek if v is not None and v != float("inf")]
        nemak = sum(1 for v in ertekek if v is None)
        vegtelenek = sum(1 for v in ertekek if v == float("inf"))
        if nemak == len(ertekek):
            eredmeny.append(fail(f"ultrasonic_{nev}", Layer.HARDWARE, Severity.CRITICAL,
                                 f"NÉMA — {nemak}/{len(ertekek)} kör válasz nélkül "
                                 f"(szakadt vezeték, nincs táp, rossz láb)"))
            continue
        szoras = statistics.pstdev(szamok) if len(szamok) > 1 else 0.0
        kozep = statistics.median(szamok) if szamok else float("inf")
        reszlet = (f"medián {kozep:.1f} cm, szórás {szoras:.2f}, "
                   f"néma {nemak}/{len(ertekek)}, üres tér {vegtelenek}/{len(ertekek)}")
        # A néma mérés HIBA, nem "szabad az út" — de egyetlen kilógó mérést a `min(3)`
        # és a következő kör úgyis elnyel. A 30% az a pont, ahol már a szenzor a gyanús.
        eredmeny.append(_cr(f"ultrasonic_{nev}", Layer.HARDWARE,
                            nemak <= 0.3 * len(ertekek), reszlet, Severity.CRITICAL))
    return eredmeny


# --- kamera ------------------------------------------------------------------

def check_kamera_szervo(settings: Settings) -> CheckResult:
    """Közép -> kis kitérés mindkét tengelyen -> vissza középre.

    A konstruktor középre áll, tehát a kiindulás ismert. A kis kitérés (15/10 fok) a
    kimért hatótávon (-79..+56 / ±54 fok) belül van, tehát nem vágásba fut. Fizikai
    igazolás csak szemmel van — lásd a modul fejlécét.
    """
    from freedroid.camera import PanTiltCamera

    kamera = PanTiltCamera(settings)
    try:
        kamera.pan("left", 15)
        kamera.pan("right", 15)
        kamera.tilt("up", 10)
        kamera.tilt("down", 10)
    except Exception as e:  # noqa: BLE001 — I2C/PCA9685 hiba is LELET, nem összeomlás
        return fail("camera_servo", Layer.HARDWARE, Severity.WARNING, repr(e))
    finally:
        kamera.close()
    # Nincs mit MÉRNI rajta: a szervónak nincs visszacsatolása, a szoftveres szög
    # visszatérése pedig számtan (15 balra + 15 jobbra = 0), nem hardver-lelet. Amit ez
    # a check bizonyít: az I2C-busz és a PCA9685 él, és a parancs végigment.
    return ok("camera_servo", Layer.HARDWARE, Severity.WARNING,
              "pan +-15 fok, tilt +-10 fok kiadva, I2C hiba nélkül — a TÉNYLEGES "
              "elfordulást nézd meg szemmel")


def _elso_kepkocka(eszkoz: str | None):
    """Az első eszköz, ami VALÓDI képkockát ad. A `/dev/video*` fele ISP/kodek csomópont
    (a Pi 5-ön 20+ darab van), azok megnyílnak, de nem adnak képet — a jelenlét tehát
    nem bizonyíték, a képkocka az."""
    import cv2

    jeloltek = [eszkoz] if eszkoz else [f"/dev/video{i}" for i in range(4)]
    for jelolt in jeloltek:
        cap = cv2.VideoCapture(jelolt)
        try:
            if not cap.isOpened():
                continue
            # Az első képkockák jellemzően feketék (az automatika még áll be) — egy
            # rögtön kiolvasott kocka EGYENLETES lenne, azaz a mérőeszköz gyártaná
            # pont azt a hibát, amit keres.
            kocka = None
            for _ in range(8):
                siker, k = cap.read()
                if siker:
                    kocka = k
                time.sleep(0.05)
            if kocka is not None:
                return jelolt, kocka
        finally:
            cap.release()
    return None, None


def check_kamera_kep(_: Settings, eszkoz: str | None) -> CheckResult:
    import numpy as np

    hol, kocka = _elso_kepkocka(eszkoz)
    if kocka is None:
        return fail("camera_frame", Layer.HARDWARE, Severity.WARNING,
                    "egyetlen /dev/video* sem adott képkockát")
    szoras = float(np.std(kocka))
    atlag = float(np.mean(kocka))
    return _cr("camera_frame", Layer.HARDWARE, szoras >= KEP_MIN_SZORAS,
               f"{hol}, {kocka.shape[1]}x{kocka.shape[0]}, szórás {szoras:.1f} "
               f"(küszöb {KEP_MIN_SZORAS}), átlag fényesség {atlag:.0f}")


# --- hang: hangszóró + mikrofon EGY méréssel ---------------------------------

def _olvas_idokorlattal(folyam, byte_szam: int, hatarido_s: float) -> bytes:
    """Legfeljebb `byte_szam` bájt, legfeljebb `hatarido_s` ideig.

    `select` + `os.read`, mert a `read(n)` a TELJES hosszra vár, és egy beragadt
    hangeszköznél sosem tér vissza. A rövid vagy üres eredmény NEM baj: a hívó abból
    "túl rövid felvétel"-t mond, ami pontos diagnózis — szemben egy örökre álló
    scripttel, ami semmit nem mond.

    A NYERS leíróról olvasunk, nem a pufferelt folyamról: a `select` a leírót nézi, a
    `BufferedReader` viszont tarthat vissza már beolvasott bájtokat, amikről a `select`
    nem tud. (Ebben a hívásban ez nem sülhet el: leftover csak akkor marad, ha a kért
    hossz kisebb a pufferben lévőnél, márpedig olyankor a hurok épp be is fejeződik.
    De egy segédfüggvénynek ne a HÍVÓJA legyen a helyességi bizonyítéka. PR #96 review.)
    """
    darabok: list[bytes] = []
    olvasva = 0
    leiro = folyam.fileno()
    veg = time.monotonic() + hatarido_s
    while olvasva < byte_szam:
        maradek = veg - time.monotonic()
        if maradek <= 0 or not select.select([leiro], [], [], maradek)[0]:
            break
        darab = os.read(leiro, min(65536, byte_szam - olvasva))
        if not darab:                   # a felvevő kilépett -> EOF
            break
        darabok.append(darab)
        olvasva += len(darab)
    return b"".join(darabok)


def _hangminta(rate: int, freq: float, masodperc: float, amp: float = 0.35) -> bytes:
    import numpy as np

    t = np.arange(int(rate * masodperc)) / rate
    return (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2").tobytes()


def hang_elemzes(pcm: bytes, rate: int, eldob_s: float = 0.25) -> tuple[float, float, float]:
    """(csúcs-frekvencia Hz, csúcs/medián arány, RMS) egy nyers 16 bites mono felvételből.

    Külön függvény, mert ez a mérés SZÁMTAN, nem hardver: hangkártya nélkül, szintetikus
    jellel tesztelhető — és pont az a fajta kód, ami csendben rosszat mond (rossz
    ablakozás, elcsúszott frekvencia-tengely), miközben a hardveren minden zöld.
    """
    import numpy as np

    minta = np.frombuffer(pcm, dtype="<i2").astype(float)
    minta = minta[int(eldob_s * rate):]     # a felvevő felfutása eldobva
    # AZ EGYENKOMPONENS LEVONÁSA NEM KOZMETIKA (teszt fogta meg): a hangkártyák visznek
    # egy eltolást, és az önmagában óriási "csúcsot" ad — az ablakozás a legalsó pár
    # vödörbe keni szét, tehát a [0] vödör kihagyása NEM elég. Enélkül egy NÉMA mikrofon
    # nagy RMS-t és nagy arányt mutat, azaz a diagnózis "a hangszóró néma" lenne,
    # miközben a mikrofon a halott.
    minta = minta - minta.mean()
    spektrum = np.abs(np.fft.rfft(minta * np.hanning(minta.size)))
    frekvenciak = np.fft.rfftfreq(minta.size, 1.0 / rate)
    csucs = int(np.argmax(spektrum))
    return (float(frekvenciak[csucs]),
            float(spektrum[csucs] / max(np.median(spektrum), 1e-9)),
            float(np.sqrt(np.mean(minta ** 2))))


def check_hang_hurok(settings: Settings) -> CheckResult:
    """HUROK-TESZT: ismert hangot játszunk le, KÖZBEN felveszünk, és a felvételben
    megkeressük ugyanazt a frekvenciát.

    Ez a script legfontosabb ötlete: a két legszubjektívebb ellenőrzést ("hallottad?",
    "hall téged?") EGY objektív mérésre cseréli. A robot hangszórója és mikrofonja
    egymás mellett van, tehát a hurok fizikailag adott.

    A lejátszás és a felvétel a BEÁLLÍTÁSOKBÓL jövő parancsokkal megy (`play_command`,
    `record_command`) — ugyanazon az úton, amit a Piper és a Whisper használ. Egy saját
    ALSA-hívás itt zöld lehetne úgy, hogy a robot közben néma.
    """
    cfg = settings.voice
    rate = cfg.stt_sample_rate
    hang = _hangminta(rate, TONE_HZ, TONE_S)

    felvevo = subprocess.Popen(shlex.split(cfg.record_command.format(rate=rate)),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lejatszo = None
    try:
        time.sleep(0.3)  # az arecord felfutása — enélkül a hang eleje kimarad
        lejatszo = subprocess.Popen(shlex.split(cfg.play_command.format(rate=rate)),
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
        _, jatek_hiba = lejatszo.communicate(hang, timeout=15)
        if lejatszo.returncode != 0:
            return fail("audio_loopback", Layer.HARDWARE, Severity.CRITICAL,
                        f"a lejátszó hibázott: "
                        f"{jatek_hiba.decode('utf-8', 'replace').strip()[:120]}")
        # A csővezeték kapacitása 64 KB; 1,3 s 16 kHz-es 16 bites mono ~42 KB, tehát
        # a felvétel NEM akad meg addig, amíg a lejátszásra várunk.
        pcm = _olvas_idokorlattal(felvevo.stdout, int(rate * 2 * (TONE_S + 0.3)),
                                  FELVETEL_HATARIDO_S)
    except subprocess.TimeoutExpired:
        return fail("audio_loopback", Layer.HARDWARE, Severity.CRITICAL,
                    "a lejátszás beragadt (foglalt hangeszköz?)")
    finally:
        # A `communicate(timeout=)` időtúllépéskor NEM öli meg a gyereket (dokumentált
        # viselkedés) — a beragadt `aplay` tehát tovább FOGVA TARTANÁ a hangeszközt, és a
        # KÖVETKEZŐ futás "foglalt eszköz"-t találna. Pont az a hiba öröklődne át, amit ez
        # az ág diagnosztizálni akar. (PR #96 review.)
        if lejatszo is not None:
            lejatszo.kill()
            lejatszo.wait()
        felvevo.kill()
        felvevo.wait()

    if len(pcm) < rate:                     # < 0,5 s (16 bites minta = 2 bájt)
        return fail("audio_loopback", Layer.HARDWARE, Severity.CRITICAL,
                    f"túl rövid felvétel ({len(pcm)} bájt) — a mikrofon nem vett fel")
    csucs_hz, arany, effektiv = hang_elemzes(pcm, rate)

    reszlet = (f"csúcs {csucs_hz:.0f} Hz (kiadva {TONE_HZ:.0f}), csúcs/medián "
               f"{arany:.0f} (küszöb {TONE_MIN_ARANY:.0f}), felvett RMS {effektiv:.0f}")
    if effektiv < 20:
        return fail("audio_loopback", Layer.HARDWARE, Severity.CRITICAL,
                    f"NÉMA MIKROFON — {reszlet}")
    rendben = abs(csucs_hz - TONE_HZ) < 50 and arany >= TONE_MIN_ARANY
    if not rendben:
        reszlet += " — a mikrofon hall, de NEM a kiadott hangot (néma hangszóró?)"
    return _cr("audio_loopback", Layer.HARDWARE, rendben, reszlet, Severity.CRITICAL)


# --- LLM + alagút ------------------------------------------------------------

def check_llm(settings: Settings) -> list[CheckResult]:
    """Nem csak az interfész: PING a felhőre, majd egy VALÓDI generálás.

    A `warmup()` a szállított döntési sorrendet futtatja (felhő, majd edge), és egy
    egytokenes kérést küld — tehát ugyanaz a hívás, ami a demón az első kérdést kiszolgálja.
    Egy puszta HTTP-200 kevés: az Ollama akkor is válaszol, ha a MODELL nincs meg.
    """
    from freedroid.llm import Backend, FallbackLLMClient

    eredmeny = []
    kod, _ki, _h = run(["ping", "-c", "2", "-W", "2", "10.0.0.1"], timeout=8.0)
    eredmeny.append(warn("wireguard_ping", Layer.NETWORK,
                         "a felhő (10.0.0.1) NEM válaszol — edge-only üzem")
                    if kod != 0 else
                    ok("wireguard_ping", Layer.NETWORK, Severity.WARNING, "10.0.0.1 él"))

    kliens = FallbackLLMClient(settings)
    t0 = time.perf_counter()
    backend = kliens.warmup()
    eltelt = time.perf_counter() - t0
    if backend is None:
        return eredmeny + [fail("llm_generate", Layer.SOFTWARE, Severity.CRITICAL,
                                f"EGYIK backend sem generált — {kliens.decision()}")]
    # A modellnevet a BEÁLLÍTÁSBÓL vesszük, nem az `active_model()`-ből: azt a `generate()`
    # állítja be, a `warmup()` nem — mérve, `None`-t adott egy sikeres bemelegítés után.
    # A név nem dísz: a "cloud"/"edge" nem árulja el, hogy a v12-t vagy a nyers bázist
    # kérdeztük meg.
    model = (settings.llm.cloud_model if backend is Backend.CLOUD
             else settings.llm.edge_model)
    return eredmeny + [ok("llm_generate", Layer.SOFTWARE, Severity.CRITICAL,
                          f"{backend.value}: {model} ({eltelt:.1f} s bemelegítés)")]


# --- lánctalpak (csak --live-motion) -----------------------------------------

def check_lanctalp(settings: Settings, meter: float) -> CheckResult:
    """LEGUTOLJÁRA, és csak kapcsolóval: ez az egyetlen check, amitől a robot elmozdul.

    A watchdog KÖZBEN fut, mert a menetet neki kell felügyelnie — a mérés így a valódi
    felállást próbálja ki, nem egy védtelen menetet.
    """
    from freedroid.motion import CytronMotionController
    from freedroid.motion.types import Direction, Speed
    from freedroid.safety import UltrasonicWatchdog

    motion = CytronMotionController(settings)
    wd = UltrasonicWatchdog(on_obstacle=motion.stop, settings=settings,
                            heading_source=lambda: (motion.heading, motion.is_turning))
    try:
        wd.start()
        t0 = time.perf_counter()
        motion.move(direction=Direction.FORWARD, distance=meter, speed=Speed.SLOW)
        oda = time.perf_counter() - t0
        time.sleep(0.5)
        t1 = time.perf_counter()
        motion.move(direction=Direction.BACKWARD, distance=meter, speed=Speed.SLOW)
        vissza = time.perf_counter() - t1
    except Exception as e:  # noqa: BLE001 — a hiba LELET
        return fail("tracks", Layer.HARDWARE, Severity.CRITICAL, repr(e))
    finally:
        wd.close()
        motion.close()

    # A rövidebb menet nem hiba: azt a watchdog is okozhatta (akadály). A LELET az, ha
    # a robot meg sem mozdult, vagy ha a két irány ideje nem egyezik.
    varhato = meter * 100 / (settings.motion.cm_per_s_at_full * 0.3)
    return _cr("tracks", Layer.HARDWARE, oda > 0.2 * varhato and vissza > 0.2 * varhato,
               f"előre {oda:.1f} s, hátra {vissza:.1f} s (várható {varhato:.1f} s/irány, "
               f"a watchdog rövidíthette)", Severity.CRITICAL)


# --- futtatás ----------------------------------------------------------------

JEL = {Status.OK: "OK  ", Status.WARN: "FIGY", Status.FAIL: "BUKÁ", Status.SKIPPED: "kih."}


def _kiir(r: CheckResult) -> None:
    kritikus = "!" if r.severity is Severity.CRITICAL else " "
    print(f"  [{JEL[r.status]}]{kritikus} {r.name:<24} {r.detail}")


def _biztonsagos(nev: str, fv, *args, layer: Layer = Layer.HARDWARE) -> list[CheckResult]:
    """Egy elhasaló check ne vigye magával a többit — a hiba maga is eredmény.

    Bring-up teszten ez nem kényelem: pont az a helyzet, amikor egy alrendszer nincs
    bekötve, és a többiről akkor is tudni akarunk. A rendszer-checkek is ezen mennek át
    (PR #96 review): a `/proc/meminfo` olvasása vagy egy hiányzó `timedatectl` a lista
    ELEJÉN hasalna el, azaz elvinné a mögötte lévő ultrahang- és hang-mérést is.
    """
    try:
        eredmeny = fv(*args)
        return eredmeny if isinstance(eredmeny, list) else [eredmeny]
    except Exception as e:  # noqa: BLE001
        return [fail(nev, layer, Severity.WARNING, f"a check elhasalt: {e!r}")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live-motion", action="store_true",
                    help="a lánctalp-teszt is fusson — A ROBOT ELMOZDUL")
    ap.add_argument("--distance", type=float, default=0.3,
                    help="a lánctalp-teszt útja méterben, irányonként (alap: 0.3)")
    ap.add_argument("--camera", default=None,
                    help="kamera-eszköz (alap: az első /dev/video*, ami képkockát ad)")
    ap.add_argument("--rounds", type=int, default=10,
                    help="ultrahang-körök száma (alap: 10)")
    ap.add_argument("--skip", default="", help="kihagyandó checkek, vesszővel "
                                               "(pl. camera_servo,audio_loopback)")
    ap.add_argument("--json", action="store_true", help="gépi kimenet")
    args = ap.parse_args()

    settings = load_settings()
    kihagy = {s.strip() for s in args.skip.split(",") if s.strip()}
    eredmenyek: list[CheckResult] = []

    def szakasz(cim: str, uj: list[CheckResult]) -> None:
        uj = [r for r in uj if r.name not in kihagy]
        if not args.json:
            print(f"\n--- {cim} ---")
            for r in uj:
                _kiir(r)
        eredmenyek.extend(uj)

    # A darabszám SZÁNDÉKOSAN nincs a szövegben: egy beírt "15 check" minden új
    # ellenőrzésnél elavul, és senki nem javítja (a `cloud_stt` már a 16. volt).
    szakasz("PASSZÍV (a freedroid-health teljes készlete)", run_checks(settings))
    szakasz("RENDSZER",
            _biztonsagos("clock", check_ora, settings, layer=Layer.SOFTWARE)
            + _biztonsagos("memory", check_memoria, settings, layer=Layer.SOFTWARE)
            + _biztonsagos("safe_mode", check_safe_mode, settings, layer=Layer.SOFTWARE))
    szakasz("ULTRAHANG", _biztonsagos("ultrasonic", check_ultrahang, settings, args.rounds))
    szakasz("KAMERA", _biztonsagos("camera_servo", check_kamera_szervo, settings)
            + _biztonsagos("camera_frame", check_kamera_kep, settings, args.camera))
    szakasz("HANG (hurok-teszt)", _biztonsagos("audio_loopback", check_hang_hurok, settings))
    szakasz("LLM + ALAGÚT", _biztonsagos("llm_generate", check_llm, settings))
    # A `kihagy` vizsgálata a HÍVÁS ELŐTT, nem a `szakasz()`-ban: az az eredményt szűri,
    # a `check_lanctalp` viszont addigra már ELMOZDÍTOTTA a robotot. Egy `--skip tracks`
    # pont attól akar megvédeni. (PR #96 review.)
    if args.live_motion and "tracks" not in kihagy:
        szakasz("LÁNCTALP (a robot mozog)",
                _biztonsagos("tracks", check_lanctalp, settings, args.distance))
    elif "tracks" not in kihagy:
        szakasz("LÁNCTALP", [CheckResult("tracks", Layer.HARDWARE, Status.SKIPPED,
                                         Severity.CRITICAL, "--live-motion nélkül")])

    jelentes = HealthReport(tuple(eredmenyek), time.time())
    if args.json:
        print(json.dumps(jelentes.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"\n=== VERDIKT: {jelentes.summary()} ===")
        for r in jelentes.critical_failures():
            print(f"  🔴 {r.name}: {r.detail}")
    return jelentes.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
