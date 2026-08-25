"""Futásidejű hangolható értékek, józan alapértelmezésekkel + KÖRNYEZETI FELÜLÍRÁS.

Az alapértelmezéseket a konstruktor egyszer ellenőrzi (tartomány-vizsgálat), tehát egy
rossz érték INDULÁSKOR hangosan bukik, nem egy félrehajtott motorban derül ki.

**Miért van env-felülírás (2026-08-18, a Pi-n mérve).** Enélkül az egyetlen mód, hogy a
roboton bármit átállíts, a FORRÁS szerkesztése volt — és ez pontosan az a hibaosztály,
ami már kétszer harapott: egy lokálisan szerkesztett `settings.py` blokkolta a
`git checkout`-ot, a Pi hetekig egy RÉGI branchen állt, és az esti health-check emiatt
jó okból NÉM ROSSZ dolgot igazolt (a régi `llama3.2:3b` tagot, nem az újat). A tanulság
nem az, hogy jobban kell figyelni, hanem hogy a gép-specifikus értéknek nem a
verziókövetett fájlban a helye.

    FREEDROID_<SZEKCIÓ>_<MEZŐ>=érték

    FREEDROID_LLM_EDGE_MODEL=szabi-3b-v12        # névtér nélküli, helyi példány
    FREEDROID_MOTION_DEG_PER_S_AT_FULL=280.0     # egy újramért kalibráció
    FREEDROID_RAG_TOP_K=1                        # gyorsabb edge-válasz, kevesebb forrás
    FREEDROID_SAFETY_STOP_THRESHOLD_CM=40        # nagyobb terem, több tartalék

A systemd `Environment=` sora ugyanezt adja a szolgáltatásnak, tehát az Ansible egy
hosztonkénti értéket úgy állít be, hogy a munkafa TISZTA marad.

Fájl-alapú configot szándékosan NEM adunk hozzá: a systemd unit és az Ansible is
env-ben gondolkodik, egy második forrás pedig csak azt a kérdést szülné, hogy melyik
nyer.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Mapping

# The retriever owns this default: it is bundled standalone (HF Space) without config.
from freedroid.rag.retriever import DEFAULT_MIN_COVERAGE


@dataclass(frozen=True)
class LLMEndpoints:
    # Cloud Ollama is reachable over WireGuard; edge Ollama is loopback-only.
    cloud_url: str = "http://10.0.0.1:11434"
    edge_url: str = "http://127.0.0.1:11434"

    # ASZIMMETRIKUS: a felhő a 8B-t viszi, az edge a 3B-t (spec, 2. szakasz). A NÉV az
    # Ollama tagje a KÉT KÜLÖN gépen — nem ugyanaz a modell két helyen, tehát nem lehet
    # egy mező.
    #
    # A DEMÓ-MODELLEK (a Teremtő, 2026-08-18), PUBLIKUS ollama.com modellként terjesztve.
    #
    # A NÉV ITT SZÓ SZERINT AZ, AMIT AZ ANSIBLE HÚZ — `ai_stack/defaults/main.yml`.
    # A névtérrel együtt: a `pull` után az `ollama list` `csaba_ajtony/szabi-3b-v12:latest`-et
    # mutat, tehát egy rövidített „szabi-3b-v12" itt 404-et adna. A két fájlnak együtt
    # kell mozognia; a `check_edge_model` pont ezt az eltérést fogja meg.
    #
    # ⚠️ A FEJLESZTŐGÉPEN más a helyzet: ott a modellek helyben, `ollama create`-tel
    # készültek, tehát névtér nélkül állnak (`szabi-8b-v12:latest`). Lokális futtatáshoz
    # ezt a két értéket kell felülírni — nem a kódot javítani.
    cloud_model: str = "csaba_ajtony/szabi-8b-v12"
    edge_model: str = "csaba_ajtony/szabi-3b-v12"

    # HÁROM külön időkorlát, és a szétválasztás a lényeg (lásd `llm/__init__.py`):
    # a `probe` dönti el, MELYIK háttér válaszol, a generálási korlátok pedig csak
    # a végső határt adják. Egy közös, rövid korlát a hideg felhőt kizárná.
    probe_timeout_s: float = 2.0
    cloud_timeout_s: float = 60.0
    edge_timeout_s: float = 90.0

    def __post_init__(self) -> None:
        for nev in ("probe_timeout_s", "cloud_timeout_s", "edge_timeout_s"):
            if getattr(self, nev) <= 0:
                raise ValueError(f"{nev} must be > 0")


@dataclass(frozen=True)
class SafetySettings:
    stop_threshold_cm: float = 25.0   # confirmed with Creator
    poll_interval_s: float = 0.05     # watchdog thread cadence
    # Per-sensor overrides, e.g. {"front": 30.0}. Read-only (frozen settings).
    per_sensor_cm: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.stop_threshold_cm <= 0:
            raise ValueError("stop_threshold_cm must be > 0")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")


@dataclass(frozen=True)
class MotionSettings:
    default_speed: float = 0.5      # 0.0–1.0 duty
    pwm_frequency_hz: int = 1000

    # MÉRVE 2026-08-17, padlón, a trimmel együtt: 100 cm-es parancsra a robot 222 cm-t
    # tett meg, tehát a korábbi 30.0-s BECSLÉS a valós sebesség kevesebb mint felét
    # mondta — a robot minden utat több mint kétszer hosszabbra hajtott volna.
    #
    # ⚠️ A szám a TRIMMEL EGYÜTT érvényes (a trim lassítja az egyik oldalt, tehát az
    # átlagsebességet is). Ha a trim változik, ezt újra kell mérni.
    #
    # A duty→sebesség viszonyt LINEÁRISnak vesszük, ami alacsony kitöltésnél nem igaz
    # (holtsáv) — ha a `move 0.5` rendre rövidebb lesz a kelleténél, ott kezdd.
    cm_per_s_at_full: float = 66.6
    # MÉRVE 2026-08-17: a 90.0-s becslés a valós fordulási sebesség HARMADÁT mondta —
    # egy 90 fokos fordulás 2.0 s helyett 0.64 s. Helyben forduláskor a két lánctalp
    # egymással szemben forog, tehát a szögsebesség jóval nagyobb, mint amit az
    # egyenes menetből "arányosítva" várnánk; ezt tényleg meg kellett mérni.
    deg_per_s_at_full: float = 280.0

    # Deadman: távolság nélküli `move` (pl. `move forward until obstacle`) sem futhat
    # örökké. Ha a watchdog szála elhal, ez az utolsó határ, ami leállítja a robotot.
    max_run_s: float = 30.0

    # OLDALANKÉNTI TRIM — a robot NEM megy egyenesen azonos kitöltésen (MÉRVE
    # 2026-08-17: balra húz, ~2 m után a folyosó falának fordul). Ez differenciál-
    # hajtásnál a VÁRT eset, nem hiba: a két motor/hajtómű/lánctalp sosem azonos.
    # Enkóder nincs, tehát nincs visszacsatolás — marad a kimért szorzó.
    #
    # A GYORSABB oldalt LASSÍTSD (szorzó < 1), ne a lassabbat gyorsítsd: teljes
    # kitöltésen már nincs hová gyorsítani, és a trim csendben hatástalan lenne.
    # MÉRVE 2026-08-17: ezekkel az értékekkel a robot 222 cm-t ment EGYENESEN.
    # A jobb oldal a gyorsabb, 8%-kal — mérés: scripts/calibrate_motion.py.
    left_duty_trim: float = 1.0
    right_duty_trim: float = 0.92

    # A két lánctalp KÖZÉPVONALÁNAK távolsága. Csak a trim kiszámításához kell
    # (az oldalirányú elsodródásból ebből jön ki a szögelfordulás).
    # MÉRVE 2026-08-17, mérőszalaggal.
    track_width_cm: float = 21.0

    def _validate_trim(self, name: str, value: float) -> None:
        if not 0.0 < value <= 1.0:
            raise ValueError(f"{name} must be within (0.0, 1.0] — lassítani lehet, "
                             f"gyorsítani nem")

    def __post_init__(self) -> None:
        if not 0.0 <= self.default_speed <= 1.0:
            raise ValueError("default_speed must be in [0.0, 1.0]")
        if self.pwm_frequency_hz <= 0:
            raise ValueError("pwm_frequency_hz must be > 0")
        if self.cm_per_s_at_full <= 0:
            raise ValueError("cm_per_s_at_full must be > 0")
        if self.deg_per_s_at_full <= 0:
            raise ValueError("deg_per_s_at_full must be > 0")
        if self.max_run_s <= 0:
            raise ValueError("max_run_s must be > 0")
        self._validate_trim("left_duty_trim", self.left_duty_trim)
        self._validate_trim("right_duty_trim", self.right_duty_trim)
        if self.track_width_cm <= 0:
            raise ValueError("track_width_cm must be > 0")


@dataclass(frozen=True)
class VoiceSettings:
    """Piper TTS. A wake word és az STT külön menet (Phase 4.2 folytatás)."""

    # A hang két fájlból áll (.onnx + .onnx.json); itt az ELŐTAG szerepel, kiterjesztés
    # nélkül — a `piper` a konfigot a modell mellől, névkonvencióval keresi.
    # ⚠️ A specben szereplő `hu_HU-anonymous-medium` NEM LÉTEZIK (mérve 2026-08-18: a
    # `rhasspy/piper-voices` magyar kínálata `anna`, `berta`, `imre`). Az `anna` ideiglenes
    # alapértelmezés — női hang, ahogy a persona kívánja —, de a VÉGSŐ választás fül-döntés,
    # és a Teremtőé. Kiterjesztés NÉLKÜLI előtag: a `.onnx` és a `.onnx.json` is kell.
    piper_model: str = "~/.local/share/piper-voices/hu_HU-anna-medium"

    # Beszédtempó: NAGYOBB = LASSABB (a Piper hosszúság-szorzója). A fiatalosabb hangzás
    # a specben elvárás, és részben a tempóból jön — de hogy MENNYI a jó, azt csak
    # hallás után lehet eldönteni, ezért kell ez a gomb. A magasság (pitch) eltolása
    # ezzel NEM oldható meg: az külön feldolgozást kívánna (sox/rubberband), és a
    # mértékét szintén hallás dönti el — ezért nincs itt találgatott alapérték.
    length_scale: float = 1.0

    # Lejátszó parancs. A Pi-n az ALSA defaultja az `/etc/asound.conf`-ból jön (a HDMI
    # helyett az USB hangszóró), ezért itt NEM adunk meg eszközt — egy beégetett
    # `-D plughw:1,0` pont azt a konfigot kerülné meg, ami már be van állítva.
    # `{rate}`: a mintavételi frekvencia a MODELL configjából jön, nem innen — a
    # `--output-raw` fejléc nélküli PCM-et ad, tehát a lejátszónak meg kell mondani a
    # formátumot. Eszközt szándékosan NEM adunk meg: az ALSA defaultja az
    # `/etc/asound.conf`-ból jön (USB hangszóró a HDMI helyett), és egy beégetett
    # `-D plughw:1,0` pont azt a konfigot kerülné meg, ami már be van állítva.
    play_command: str = "aplay -q -r {rate} -f S16_LE -t raw -"

    # A beszéd FELSŐ HATÁRA. Nem teljesítmény-kérdés: ha a hangeszköz foglalt, az `aplay`
    # megállhat a megnyitáson anélkül, hogy kilépne — olyankor a csővezeték BERAGAD, és a
    # robot a színpadon némán, örökre várna. Egy hangos hiba mindig jobb, mint egy néma
    # megállás. 17 szó kimondása a Pi-n 9,8 s volt (mérve), tehát a 60 s bőséges tartalék.
    speak_timeout_s: float = 60.0

    # --- STT: whisper.cpp (natív bináris, NEM pip-csomag) ---
    #
    # A bináris a forrásból fordított whisper.cpp-ből jön, tehát NINCS sem a venv-ben,
    # sem a PATH-on — ezért teljes útvonal az alapérték. Ha valaki mégis PATH-ra teszi,
    # elég a puszta nevet megadni: a kód olyankor a `find_voice_binary`-re esik vissza,
    # ugyanarra a szabályra, ami a Pipert is megtalálja.
    whisper_binary: str = "~/whisper.cpp/build/bin/whisper-cli"

    # A `small` a magyarhoz az a méret, ahol a felismerés használhatóvá válik; a
    # `q5_1` kvantálás ARM-en érdemben gyorsít. A `base` a gyors tartalék — a váltás
    # egy env-felülírás, nem kódmódosítás.
    whisper_model: str = "~/.local/share/whisper-models/ggml-small-q5_1.bin"

    # A nyelv KÖTÖTT, nem automatikus. Az autodetekció egy rövid magyar parancson
    # ("Szabi, gyere ide") simán szlovákot vagy csehet tippel, és onnantól a
    # transzkripció zagyva — a robot pedig egy zagyva mondatra válaszolna. A magyar
    # egyébként is a szuverenitás-üzenet része, nem futásidejű döntés.
    stt_language: str = "hu"
    stt_threads: int = 4
    stt_timeout_s: float = 60.0

    # SZÓTÁR-PROMPT — nem finomhangolás, hanem MŰKÖDÉSI FELTÉTEL. Mérve 2026-08-25,
    # ugyanazon a hangmintán:
    #   prompt nélkül:  "Mit tanít aja TENVRÍT a szabadsagról?"
    #   prompttal:      "mit tanít a YOTENGRIT a szabadsagról?"
    # A "Yotengrit" kitalált szó, egyetlen Whisper-modell szótárában sincs benne — a
    # robot legfontosabb fogalmát értené félre nélküle. A prompt a dekódolást a felsorolt
    # szavak felé billenti (a modellt NEM módosítja).
    #
    # ⚠️ NE tömd tele: a prompt a 224 tokenes kontextusból eszik, és egy hosszú lista
    # olyan szavakat is beleerőltet a szövegbe, amik el sem hangzottak.
    stt_prompt: str = "Szabi, Yotengrit, Teremtő, szabadság, Büün, tudók."

    # --- VAD: energia-alapú beszédvég-detektálás ---
    #
    # A Whisper 16 kHz-et vár; más rátán némán ROSSZUL ismer fel (nem hibázik, csak
    # rosszul érti), ezért ez nem szabadon állítható kényelmi érték.
    stt_sample_rate: int = 16000
    record_command: str = "arecord -q -r {rate} -f S16_LE -c 1 -t raw -"

    # A küszöb NEM beégetett szám: a felvétel elején megmérjük a zajszintet, és ahhoz
    # képest szorzunk. Egy fix érték egy konferencia-teremben (zajos) és egy szobában
    # (csendes) nem lehet ugyanaz — a demó pedig a zajos helyen lesz.
    vad_calib_s: float = 0.3        # ennyiből becsüljük a zajszintet
    vad_snr: float = 3.0            # a zajszint ennyiszerese számít beszédnek
    vad_min_rms: float = 120.0      # abszolút alsó korlát (néma mikrofonnál a szorzó 0 lenne)
    vad_silence_s: float = 0.8      # ennyi csend után vége a mondatnak
    vad_max_s: float = 15.0         # felső korlát: egy beragadt mikrofon ne vegyen fel örökké
    vad_start_timeout_s: float = 10.0   # ennyit várunk a beszéd KEZDETÉRE
    vad_preroll_s: float = 0.3      # a beszédkezdet ELŐTTI ennyi másodperc is bekerül

    def __post_init__(self) -> None:
        if self.length_scale <= 0:
            raise ValueError("length_scale must be > 0")
        if self.speak_timeout_s <= 0:
            raise ValueError("speak_timeout_s must be > 0")
        if self.stt_threads <= 0:
            raise ValueError("stt_threads must be > 0")
        if self.stt_timeout_s <= 0:
            raise ValueError("stt_timeout_s must be > 0")
        if self.stt_sample_rate <= 0:
            raise ValueError("stt_sample_rate must be > 0")
        for nev, ertek in (("vad_calib_s", self.vad_calib_s), ("vad_snr", self.vad_snr),
                           ("vad_min_rms", self.vad_min_rms),
                           ("vad_silence_s", self.vad_silence_s),
                           ("vad_max_s", self.vad_max_s),
                           ("vad_start_timeout_s", self.vad_start_timeout_s)):
            if ertek <= 0:
                raise ValueError(f"{nev} must be > 0")
        if self.vad_preroll_s < 0:
            raise ValueError("vad_preroll_s must be >= 0")
        if self.vad_max_s <= self.vad_silence_s:
            raise ValueError("vad_max_s legyen nagyobb a vad_silence_s-nél")
        # Ugyanaz az indoklás, mint a play_command-nál: egy elgépelt helyőrző csak a
        # FELVÉTEL pillanatában bukna ki — vagyis a színpadon.
        try:
            self.record_command.format(rate=16000)
        except (KeyError, IndexError) as e:
            raise ValueError(f"record_command ismeretlen helyőrzőt tartalmaz ({e}); "
                             f"csak a {{rate}} tölthető ki") from e
        # A `{rate}` helyőrzőt a `PiperTTS` tölti ki. Egy elgépelt felülírás (pl.
        # `{sample_rate}`) enélkül csak a BESZÉD pillanatában bukna ki — vagyis a
        # színpadon. A validáció INDULÁSKOR ugyanazt mondja meg, órákkal korábban.
        try:
            self.play_command.format(rate=22050)
        except (KeyError, IndexError) as e:
            raise ValueError(f"play_command ismeretlen helyőrzőt tartalmaz ({e}); "
                             f"csak a {{rate}} tölthető ki") from e


@dataclass(frozen=True)
class RAGSettings:
    # Offline BM25 retrieval over the Yotengrit corpus. corpus_path="" -> the loader
    # uses its repo-default (training/rag/yotengrit_corpus.json).
    enabled: bool = True
    corpus_path: str = ""
    top_k: int = 3
    min_score: float = 0.0       # a chunk must score strictly above this to be returned
    title_boost: int = 2         # heading tokens weighted Nx in the BM25 index
    min_coverage: float = DEFAULT_MIN_COVERAGE   # idf-weighted query coverage gate

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be > 0")
        if self.min_score < 0:
            raise ValueError("min_score must be >= 0")
        if self.title_boost < 1:
            raise ValueError("title_boost must be >= 1")
        if not 0.0 <= self.min_coverage <= 1.0:
            raise ValueError("min_coverage must be within 0.0–1.0")


@dataclass(frozen=True)
class CameraSettings:
    """Pan/tilt szervók a PCA9685-ön.

    MINDEN érték MÉRT (2026-08-25, `scripts/calibrate_camera.py`, a felszerelt kamerán),
    és TENGELYENKÉNT KÜLÖN — ez nem óvatosság, hanem lelet: a két szervó skálája 19%-kal
    tér el (0,0133 vs 0,0112 ms/fok), és a mechanikai középük sem esik egybe. Egyetlen
    közös érték az egyik tengelyre biztosan hazudna.

    Env-ből felülírható (`FREEDROID_CAMERA_PAN_MS_PER_DEG` stb.): a kalibrációs érték a
    GÉPHEZ tartozik, nem a repóhoz — egy szervócsere vagy egy áthelyezett horn átírja.
    """

    pwm_frequency_hz: int = 50      # a hobbiszervók szabványos kerete (20 ms)

    # A MECHANIKAI közép, tengelyenként. A pané NEM 1,5 ms: a felszerelt tartón az
    # egyenesen előre 1,65 ms-nál van. A tilté szándékosan olyan, hogy a kamera kissé
    # FELFELÉ nézzen — a robot a földön áll és álló emberre néz.
    pan_centre_ms: float = 1.65
    tilt_centre_ms: float = 1.50

    # Hány ms egy fok. KÉT ÁLLÓ HELYZET szögéből, nem egy mozdulat megsaccolásából.
    #
    # ⚠️ A tilt értéke JAVÍTVA 0,0112-ről (2026-08-25): a végállások közti TELJES
    # kitérés mérése 160 fokot adott, egy közép körüli ellenőrzés viszont 0,336 ms-ra
    # pontosan 20 fokot -> 0,0168. Az utóbbi a hiteles, és a különbség 50%.
    #
    # A TANULSÁG A MÓDSZERRŐL SZÓL: a két végállás közti NAGY szöget rosszul becsli az
    # ember (a kamera ott le-föl néz, nincs mihez viszonyítani), egy 20-30 fokos
    # kitérést a közép körül viszont jól. A `calibrate_camera.py` ezért záró
    # ELLENŐRZÉST is végez — ez a hibát elfogta volna.
    pan_ms_per_deg: float = 0.0133
    tilt_ms_per_deg: float = 0.0168

    # A biztonságos pulzus-sáv, VÉGIGPRÓBÁLVA kifelé lépegetve (--explore): eddig megy a
    # szervó anélkül, hogy nekifeszülne. A korábbi 1,0-2,0 ÓVATOS TIPP volt, és drágán:
    # a mért skálával csak ±25 fokot engedett, amiben egy "fordulj balra 45 fokot"
    # mindig vágásba futott. A valóság ±68 (pan) / ±80 (tilt) fok.
    min_ms: float = 0.60
    max_ms: float = 2.40

    # HOLTJÁTÉK (a fogaskerekek hézaga), tengelyenként mérve: ugyanarra a pulzusra
    # alulról és felülről közelítve ennyivel áll meg máshol a kamera. EZ okozta, hogy a
    # gesztusok után nem pontosan a kiindulóba tért vissza — a szoftver a helyes pulzust
    # adta ki. A pan 10 foka nem elhanyagolható.
    pan_backlash_deg: float = 10.0
    tilt_backlash_deg: float = 5.0

    # Gesztusok. A bólintás kicsi és FÜRGE (egy lassú bólintás nem bólintás).
    # ⚠️ A fok-értékek a JÓVÁHAGYOTT mozgásból lettek visszaszámolva: a Teremtő a régi
    # (rossz) skálán látta és fogadta el őket, tehát a FIZIKAI kitérést tartjuk meg, nem
    # a számot. A bólintás pulzus-kitérése végig 0,235 ms; a skála javításával (0,0112 ->
    # 0,0168) a hozzá tartozó FOK lett kisebb, a mozdulat ugyanaz maradt.
    nod_deg: float = 14.0
    nod_count: int = 2
    step_s: float = 0.35            # egy bólintás-lépés kivárása

    # A pásztázás MÁS: a kamerának LÁTNIA kell közben (a Teremtő, 2026-08-25 — a gyors
    # változat "nem fog látni semmit"). A szervónak nincs sebesség-bemenete: egy nagy
    # lépésre teljes gyorsasággal odaugrik. Lassítani CSAK úgy lehet, hogy a mozgást kis
    # lépésekre bontjuk. A 30 fok / 45 fok/s ugyanaz a FIZIKAI pásztázás, amit a Teremtő
    # jóváhagyott (régi 20 fok / 30 fok/s @ 0,020 skálán).
    scan_deg: float = 30.0
    scan_deg_per_s: float = 45.0
    scan_step_deg: float = 2.0      # ekkora lépésekben, hogy folyamatosnak lássék

    def __post_init__(self) -> None:
        if self.pwm_frequency_hz <= 0:
            raise ValueError("pwm_frequency_hz must be > 0")
        if self.pan_ms_per_deg <= 0 or self.tilt_ms_per_deg <= 0:
            raise ValueError("a ms_per_deg értékek > 0 kell legyenek")
        for nev, kozep in (("pan", self.pan_centre_ms), ("tilt", self.tilt_centre_ms)):
            if not self.min_ms < kozep < self.max_ms:
                raise ValueError(f"min_ms < {nev}_centre_ms < max_ms kell legyen")
        # A keretnél hosszabb pulzus értelmezhetetlen: 50 Hz-en a 20 ms a teljes periódus.
        if self.max_ms >= 1000.0 / self.pwm_frequency_hz:
            raise ValueError("max_ms nem érheti el a PWM-keretet (1000/frekvencia ms)")
        if self.pan_backlash_deg < 0 or self.tilt_backlash_deg < 0:
            raise ValueError("a holtjáték nem lehet negatív")
        if self.nod_count <= 0 or self.nod_deg <= 0 or self.scan_deg <= 0:
            raise ValueError("nod_count, nod_deg, scan_deg mind > 0 kell legyen")
        if self.step_s <= 0:
            raise ValueError("step_s must be > 0")
        if self.scan_deg_per_s <= 0 or self.scan_step_deg <= 0:
            raise ValueError("scan_deg_per_s és scan_step_deg > 0 kell legyen")


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoints = field(default_factory=LLMEndpoints)
    safety: SafetySettings = field(default_factory=SafetySettings)
    motion: MotionSettings = field(default_factory=MotionSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)


# Az env-változók, amiket MÁS modulok olvasnak. Azért kell a lista, hogy az elgépelt
# felülírásokra figyelmeztethessünk anélkül, hogy ezekre is rászólnánk.
_EGYEB_ENV = frozenset({
    "FREEDROID_ASSUME_PI", "FREEDROID_GPIOCHIP", "FREEDROID_HEALTH_STATUS",
    "FREEDROID_SAFE_MODE_FLAG", "FREEDROID_TRANSCRIPT_LOG", "FREEDROID_MOTOR_TEST",
    "FREEDROID_DEBUG",
})

_SZEKCIOK = {"LLM": ("llm", LLMEndpoints), "SAFETY": ("safety", SafetySettings),
             "MOTION": ("motion", MotionSettings), "VOICE": ("voice", VoiceSettings),
             "RAG": ("rag", RAGSettings), "CAMERA": ("camera", CameraSettings)}

# Csak skalár mezők írhatók felül. A `per_sensor_cm` (Mapping) szándékosan kimarad:
# egy env-be sűrített dict saját mini-nyelvtant kívánna, és az elgépelése némán
# rossz küszöböt adna — épp azt a hibát, ami ellen ez az egész készült.
_IGAZ = {"1", "true", "yes", "igen", "on"}
_HAMIS = {"0", "false", "no", "nem", "off"}


def _ertek(kulcs: str, nyers: str, tipus: str):
    """Sztring -> a mező típusa. Ismeretlen/rossz érték HANGOS hiba.

    A bool külön eset, és nem kényeskedés: a `bool("hamis")` Pythonban IGAZ. Egy
    `FREEDROID_RAG_ENABLED=hamis` tehát némán BEkapcsolva hagyná a RAG-ot.
    """
    if tipus == "bool":
        kicsi = nyers.strip().lower()
        if kicsi in _IGAZ:
            return True
        if kicsi in _HAMIS:
            return False
        raise ValueError(f"{kulcs}={nyers!r} — logikai értéket vártam "
                         f"({'/'.join(sorted(_IGAZ))} vagy {'/'.join(sorted(_HAMIS))})")
    try:
        ertek = {"str": str, "int": int, "float": float}[tipus](nyers)
    except (KeyError, ValueError) as e:
        raise ValueError(f"{kulcs}={nyers!r} — nem értelmezhető {tipus}-ként") from e

    # A `float("nan")` és a `float("inf")` ÉRVÉNYES bemenet a `float()`-nak, és a NaN
    # MINDEN összehasonlítása hamis — tehát a `__post_init__` tartomány-ellenőrzései
    # (`<= 0`, `not 0.0 < x <= 1.0`) NÉMÁN átengednék. A hatásuk viszont nem ártalmatlan:
    # egy NaN `cm_per_s_at_full` NaN menetidőt ad, egy `inf` pedig NULLA hosszút, azaz a
    # robot meg sem mozdul — mindkettő némán. (PR #88 review.)
    if tipus == "float" and not math.isfinite(ertek):
        raise ValueError(f"{kulcs}={nyers!r} — véges számot vártam "
                         f"(a NaN és a végtelen kicselezi a tartomány-ellenőrzést)")
    return ertek


def _tipusnev(annotacio: object) -> str:
    """A mező típusának NEVE, akárhogyan is tárolja a Python az annotációt.

    A `from __future__ import annotations` miatt ma minden annotáció SZTRING, tehát
    `f.type == "float"`. Ha viszont ez az import valaha eltűnik (a PEP 649 óta reális
    takarítás), az annotációk kiértékelt TÍPUSOBJEKTUMOK lesznek, és egy sztring-
    összevetés egyetlen mezőre sem illeszkedne — vagyis MINDEN env-felülírás NÉMÁN
    abbahagyná a működését, és a robot az alapértelmezésekkel futna tovább.

    Pontosan az a csendes sodródás, ami ellen ez a modul készült. (PR #88 review.)
    A `test_a_felismert_kulcsok_keszlete_ROGZITETT` erre külön ráfeszül.
    """
    if isinstance(annotacio, type):
        return annotacio.__name__
    return str(annotacio)


def _szekciobol(cls, elonev: str, kornyezet) -> tuple[object, set[str]]:
    """Egy szekció példánya az env-ből. Visszaadja a FELISMERT kulcsokat is."""
    kwargs, ismert = {}, set()
    for f in fields(cls):
        tipus = _tipusnev(f.type)
        if tipus not in ("str", "int", "float", "bool"):
            continue
        kulcs = f"FREEDROID_{elonev}_{f.name.upper()}"
        ismert.add(kulcs)
        if (nyers := kornyezet.get(kulcs)) is not None:
            kwargs[f.name] = _ertek(kulcs, nyers, tipus)
    return cls(**kwargs), ismert


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """A hatályos beállítások: alapértelmezések + `FREEDROID_<SZEKCIÓ>_<MEZŐ>` felülírás.

    A validáció VÁLTOZATLANUL fut (a dataclassok `__post_init__`-je), tehát egy
    tartományon kívüli env-érték ugyanúgy indulásnál bukik, mint egy rossz default.
    """
    kornyezet = os.environ if env is None else env
    reszek, ismert = {}, set()
    for elonev, (mezo, cls) in _SZEKCIOK.items():
        reszek[mezo], kulcsok = _szekciobol(cls, elonev, kornyezet)
        ismert |= kulcsok

    # ELGÉPELT FELÜLÍRÁS: némán az alapértelmezéssel futni pontosan az a csendes
    # sodródás, ami ellen ez a modul készült. Figyelmeztetés, nem hiba: egy ismeretlen
    # FREEDROID_* változó miatt a robot ne álljon meg a színpadon.
    for kulcs in sorted(k for k in kornyezet if k.startswith("FREEDROID_")):
        if kulcs not in ismert and kulcs not in _EGYEB_ENV:
            print(f"settings: ISMERETLEN felülírás, FIGYELMEN KÍVÜL HAGYVA: {kulcs} "
                  f"(elgépelés? az alapértelmezés marad érvényben)", file=sys.stderr)
    return Settings(**reszek)
