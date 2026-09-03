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
    stop_threshold_cm: float = 25.0   # confirmed with Creator; a FAST duty (0,65) fékútja 24,6 cm
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
    default_speed: float = 0.6      # 0.0–1.0 UTAZÓ duty (az indítás a `kick_duty`, lásd lent)
    # INDÍTÓ LÖKÉS + RÁMPA (mérve 2026-09-03, 10,9 V-os akku, padló): 0,5 duty-n a motor
    # zúg, de a tapadási súrlódást nem lépi át; 0,8-on megy, de „rángat, hirtelen indul
    # és áll" (a Teremtő). Ezért az indulás `kick_s` ideig `kick_duty`-val megy (a
    # súrlódás átlépéséhez), utána az utazó duty, a végén `ramp_s` alatt lineárisan 0-ra
    # (a watchdog `stop()`-ja NEM rámpáz: az azonnali). `ramp_s = 0` kikapcsolja.
    # Hogy az utazó 0,6 fenntartja-e a mozgást, MÉRENDŐ — a csavarok:
    # FREEDROID_MOTION_DEFAULT_SPEED / KICK_DUTY / KICK_S / RAMP_S.
    kick_duty: float = 0.85
    kick_s: float = 0.15
    ramp_s: float = 0.4
    pwm_frequency_hz: int = 1000

    # ÚJRAMÉRVE 2026-08-26, TELI AKKUN, a mai trimmel: 200 cm-es parancsra a robot
    # 230 cm-t tett meg (115%), és ez KÉT KÜLÖNBÖZŐ PADLÓN, kétszer ugyanannyi.
    # A korábbi 66.6 (2026-08-17) tehát 15%-kal alábecsülte a sebességet.
    #
    # A szám FÜGGETLEN megerősítést is kapott, más módszerrel: a `watchdog_e2e.py`
    # közelítés-nyoma szerint a robot 38,5 cm/s-mal záródott az akadályra 0,5
    # kitöltésen (= ~77 cm/s teljesen). Két külön mérés, ugyanaz az érték.
    #
    # ⚠️ A szám a TRIMMEL EGYÜTT érvényes (a trim lassítja az egyik oldalt, tehát az
    # átlagsebességet is). Ha a trim változik, ezt újra kell mérni.
    # ⚠️ AKKUFÜGGŐ: ez a mérés teli akkun készült. Merülő akkuval a robot lassul, azaz
    # a parancsolt utaknál RÖVIDEBBET tesz meg — a hiba iránya ártalmatlan.
    #
    # A duty→sebesség viszonyt LINEÁRISnak vesszük, ami alacsony kitöltésnél nem igaz
    # (holtsáv) — ha a `move 0.5` rendre rövidebb lesz a kelleténél, ott kezdd.
    cm_per_s_at_full: float = 76.6
    # ÚJRAMÉRVE 2026-08-26, teli akkun, a mai trimmel: 360 fokos parancsra 420 fok
    # (117%). A 2026-08-17-i 280.0 tehát ugyanabba az irányba tévedett, mint a
    # menetsebesség. (A 90.0-s eredeti BECSLÉS a valós érték harmadát mondta: helyben
    # forduláskor a két lánctalp egymással SZEMBEN forog, tehát a szögsebesség sokkal
    # nagyobb, mint amit az egyenes menetből "arányosítva" várnánk.)
    #
    # A mérés a MAI trimmel készült (jobb oldal 0,991) — ez nem mellékes: a fordulás
    # sebessége a két oldal kitöltésének ÖSSZEGÉN múlik, tehát egy trim-változás ezt
    # is elmozdítja. A 0,991 -> 0,997 lépés 0,6%, ami ezen a számon nem látszik.
    deg_per_s_at_full: float = 326.7

    # A LÁNCTALP KIFUTÁSA a `stop()` UTÁN — mért fizikai tulajdonság, mint a fenti
    # kettő, és ugyanúgy ide tartozik: a fékút-büdzsé enélkül a valóság ~60%-át
    # számolná, épp a veszélyes irányban.
    #
    # MÉRVE 2026-08-26, három éles menetből (`scripts/watchdog_e2e.py --live-motion`):
    # 2,9 cm @ 23 cm/s, 4,0 cm @ 38 cm/s, 7,1 cm @ 38 cm/s MÁS PADLÓN = 126/104/185 ms.
    # A legrosszabbat vesszük. A döntő megfigyelés: a `stop()` maga 0,2 ms, tehát ez NEM
    # szoftveres késleltetés — mechanika, és a FELÜLET érdemben számít (a csúszósabbon
    # hosszabb). A helyszínen érdemes újramérni: FREEDROID_MOTION_COAST_S.
    coast_s: float = 0.20

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
    #
    # ÚJRAMÉRVE 2026-08-26: a korábbi 0.92 TÚLKORREKCIÓ volt. Azzal a robot JOBBRA
    # húzott (30 cm / 130 cm), azaz a jobb oldal lett túl lassú — a 8%-os fékezés a
    # valós különbség sokszorosa. A mai érték 230 cm alatt 8 cm elsodródásból jött.
    #
    # ⚠️ A TRIM PADLÓFÜGGŐ, és ezt ma meg is mértük: ugyanaz a beállítás az egyik
    # felületen alig húzott, a másikon sokkal jobban. Egy konstans szorzó tehát
    # KOMPROMISSZUM, nem abszolút igazság — a helyszínen érdemes ránézni, és a
    # demó-manővereket rövid szakaszokra tervezni, nem hosszú egyenesekre.
    # Felülírás újramérés nélkül: FREEDROID_MOTION_RIGHT_DUTY_TRIM.
    left_duty_trim: float = 1.0
    right_duty_trim: float = 0.997

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
        if self.coast_s < 0:
            raise ValueError("coast_s must be >= 0")
        self._validate_trim("left_duty_trim", self.left_duty_trim)
        self._validate_trim("right_duty_trim", self.right_duty_trim)
        if self.track_width_cm <= 0:
            raise ValueError("track_width_cm must be > 0")
        if not 0.0 < self.kick_duty <= 1.0 or self.kick_s < 0 or self.ramp_s < 0:
            raise ValueError("kick_duty (0,1], kick_s >= 0, ramp_s >= 0 kell legyen")


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

    # FIGYELJ-csipogás a felvétel ELŐTT (a Teremtő, 2026-09-03: a gombnyomás visszajelzés
    # nélkül nem egyértelmű). `listen_beep_s = 0` kikapcsolja. Nem veszi fel magát: a
    # felvétel a hang UTÁN indul, és a lejátszó/felvevő két külön eszköz.
    listen_beep_hz: float = 880.0
    listen_beep_s: float = 0.12

    # --- STT: whisper.cpp (natív bináris, NEM pip-csomag) ---
    #
    # PUSZTA NÉV, tehát a `find_voice_binary` keresi meg (venv, majd PATH) — UGYANAZ a
    # szabály, ami a Pipert is megtalálja, és amit a `health.check_voice_binaries`
    # használ. Ez nem kényelmi döntés: ha a health-check máshol keresné a binárist, mint
    # a tényleges hívás, a kettő CSENDBEN elcsúszhatna (a health "hiányzik"-ot mondana
    # egy működő roboton, vagy fordítva). Az Ansible ezért a `/usr/local/bin`-be
    # telepíti, nem a build-könyvtárban hagyja. Teljes útvonal is megadható.
    whisper_binary: str = "whisper-cli"

    # A `small` a magyarhoz az a méret, ahol a felismerés használhatóvá válik; a
    # `q5_1` kvantálás ARM-en érdemben gyorsít. A `base` a gyors tartalék — a váltás
    # egy env-felülírás, nem kódmódosítás.
    whisper_model: str = "~/.local/share/whisper-models/ggml-small-q5_1.bin"

    # A nyelv KÖTÖTT, nem automatikus. Az autodetekció egy rövid magyar parancson
    # ("Szabi, gyere ide") simán szlovákot vagy csehet tippel, és onnantól a
    # transzkripció zagyva — a robot pedig egy zagyva mondatra válaszolna. A magyar
    # egyébként is a szuverenitás-üzenet része, nem futásidejű döntés.
    # --- FELHŐS STT: ugyanaz a whisper.cpp, GPU-n, a WireGuard-alagút túlvégén ---
    #
    # MIÉRT: az STT a lánc leglassabb eleme, és a késleltetése ~ÁLLANDÓ, a hang hosszától
    # FÜGGETLENÜL (8,9-15 s a `small`-lal, mérve 2026-08-25) — a Whisper minden bemenetet
    # 30 s-os ablakra tölt, tehát a kódoló mindig ugyanannyit dolgozik. A felhős 8B ehhez
    # képest 1,3 s. A GPU-s `large-v3-turbo` másodperc alatt végez, ÉS a tulajdonneveket
    # is jobban viszi — a "Szabi" -> "Szabiget/Szabbi/Szabü" hibák nagy része innen jön.
    #
    # A SZUVERENITÁS NEM SÉRÜL: ez a SAJÁT felhőnk a saját alagutunkban, nem vendor API.
    # Ha mégis offline demót akarunk, `stt_prefer_cloud=false` (vagy egyszerűen nincs
    # alagút) — a visszaesés a Pi-re automatikus, ugyanaz a létra, ami az LLM-nél működik.
    stt_cloud_url: str = "http://10.0.0.1:8080"
    stt_prefer_cloud: bool = True
    # Külön időkorlát: a felhős út hálózatot is tartalmaz, de GPU-n fut. Ha ennyi alatt
    # nem végez, az edge gyorsabban ad választ, mint a további várakozás.
    stt_cloud_timeout_s: float = 20.0
    # A DÖNTÉS próbája, nem a munkáé. Rövid, mert minden mondatnál lefut, és a lényege,
    # hogy egy HALOTT alagútnál ne 160 KB hang feltöltése után derüljön ki a baj.
    stt_cloud_probe_timeout_s: float = 2.0

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
        if self.listen_beep_s < 0 or (self.listen_beep_s > 0 and self.listen_beep_hz <= 0):
            raise ValueError("listen_beep_s >= 0, és bekapcsolva listen_beep_hz > 0 kell legyen")
        if self.stt_threads <= 0:
            raise ValueError("stt_threads must be > 0")
        if self.stt_timeout_s <= 0:
            raise ValueError("stt_timeout_s must be > 0")
        if self.stt_sample_rate <= 0:
            raise ValueError("stt_sample_rate must be > 0")
        for nev, ertek in (("stt_cloud_timeout_s", self.stt_cloud_timeout_s),
                           ("stt_cloud_probe_timeout_s", self.stt_cloud_probe_timeout_s),
                           ("vad_calib_s", self.vad_calib_s), ("vad_snr", self.vad_snr),
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
class PowerSettings:
    """Akku-feszültség az ADS1115-ön (I2C 0x48, AIN0, feszültségosztón át).

    MÉRVE 2026-09-03: a 0x48 a gyári cím, AIN0 = 3,143 V az akkun mért 12,3 V mellett
    → az osztó 3,91:1. A `divider` a kalibrációs csavar: egy ellenállás-csere vagy egy
    másik osztó ITT javítandó (`FREEDROID_POWER_DIVIDER`), nem a kódban. A cellánkénti
    küszöbök a Teremtő csipogó feszültségmérőjéhez igazodnak (riasztás 3,4 V/cella);
    a kritikus szint alatt a LiPo VISSZAFORDÍTHATATLANUL sérül, ezért az a motor-tiltás.
    """

    i2c_bus: str = "/dev/i2c-1"
    ads_address: int = 0x48
    divider: float = 3.91             # osztó aránya: V_akku = V_AIN0 × divider
    cells: int = 3                    # 3S LiPo
    warn_v_per_cell: float = 3.4      # WARNING (health) — a csipogó is itt szól
    critical_v_per_cell: float = 3.2  # CRITICAL: motor tilt + "Pihennem kell, Teremtőm!"
    check_every_s: float = 60.0       # az orchestrator ilyen sűrűn olvassa

    def __post_init__(self) -> None:
        if self.divider <= 0 or self.cells <= 0 or self.check_every_s <= 0:
            raise ValueError("divider, cells és check_every_s > 0 kell legyen")
        if not 0 < self.critical_v_per_cell < self.warn_v_per_cell:
            raise ValueError("0 < critical_v_per_cell < warn_v_per_cell kell legyen")

    @property
    def warn_v(self) -> float:
        return self.warn_v_per_cell * self.cells

    @property
    def critical_v(self) -> float:
        return self.critical_v_per_cell * self.cells


@dataclass(frozen=True)
class LedSettings:
    """WS2812 státusz-gyűrű (spec §6). A `count` MÉRENDŐ, amikor a gyűrű rákerül a
    GPIO-ra (`FREEDROID_LED_COUNT`); a fényerő a konferencia-teremhez hangolandó."""

    enabled: bool = True
    count: int = 12
    brightness: float = 0.3
    fps: float = 30.0

    def __post_init__(self) -> None:
        if self.count <= 0 or self.fps <= 0:
            raise ValueError("count és fps > 0 kell legyen")
        if not 0.0 < self.brightness <= 1.0:
            raise ValueError("brightness 0 és 1 között kell legyen")


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoints = field(default_factory=LLMEndpoints)
    safety: SafetySettings = field(default_factory=SafetySettings)
    motion: MotionSettings = field(default_factory=MotionSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    power: PowerSettings = field(default_factory=PowerSettings)
    led: LedSettings = field(default_factory=LedSettings)


# Az env-változók, amiket MÁS modulok olvasnak. Azért kell a lista, hogy az elgépelt
# felülírásokra figyelmeztethessünk anélkül, hogy ezekre is rászólnánk.
_EGYEB_ENV = frozenset({
    "FREEDROID_ASSUME_PI", "FREEDROID_GPIOCHIP", "FREEDROID_HEALTH_STATUS",
    "FREEDROID_SAFE_MODE_FLAG", "FREEDROID_TRANSCRIPT_LOG", "FREEDROID_MOTOR_TEST",
    "FREEDROID_DEBUG",
})

_SZEKCIOK = {"LLM": ("llm", LLMEndpoints), "SAFETY": ("safety", SafetySettings),
             "MOTION": ("motion", MotionSettings), "VOICE": ("voice", VoiceSettings),
             "RAG": ("rag", RAGSettings), "CAMERA": ("camera", CameraSettings),
             "POWER": ("power", PowerSettings), "LED": ("led", LedSettings)}

# Csak skalár mezők írhatók felül. A `per_sensor_cm` (Mapping) szándékosan kimarad:
# egy env-be sűrített dict saját mini-nyelvtant kívánna, és az elgépelése némán
# rossz küszöböt adna — épp azt a hibát, ami ellen ez az egész készült.
_IGAZ = {"1", "true", "yes", "igen", "on"}
_HAMIS = {"0", "false", "no", "nem", "off"}


def debug_mode() -> bool:
    """Fut-e a robot DEBUG POSZTÚRÁBAN. Alapból NEM, és a polaritás a lényeg.

    A Teremtő döntése (2026-08-10): a demóig hibakereső posztúra kell (átirat-napló,
    bőbeszédű naplózás), a demóra viszont a cél az, hogy *egy ellopott robot vagy
    SD-kártya ne adjon semmit, ami nincs benne a publikus GitHub-repóban*. Ez elérhető
    bár, mert a modell, a prompt és a korpusz SZÁNDÉKOSAN publikus — egyedül a rögzített
    beszélgetés bukna el rajta.

    Ezért ALAPÉRTELMEZÉSBEN HAMIS: egy kapcsoló, amit ki KELL kapcsolni, előbb-utóbb
    bekapcsolva marad, és a hibája a Teremtő beszélgetése egy lopható kártyán. Így a
    "elfelejtettem" annyit tesz: "nem naplózott".

    A szó szerinti értéklista nem pedantéria: `bool("hamis")` Pythonban IGAZ.
    """
    return os.environ.get("FREEDROID_DEBUG", "").strip().lower() in _IGAZ


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
