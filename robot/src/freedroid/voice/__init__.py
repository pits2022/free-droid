"""Voice pipeline: wake word → STT → (LLM) → TTS, plus VAD.

A hang-lánc a Pi-n fut (szuverenitás), EGY kivétellel: az STT-nek van felhős ága is —
ugyanaz a whisper.cpp, GPU-n, a SAJÁT alagutunk túlvégén (nem vendor API). A visszaesés
automatikus, tehát alagút nélkül a robot ugyanúgy ért magyarul, csak lassabban.

  - wake word: openWakeWord ("Szabi")
  - STT: whisper.cpp (Hungarian) — felhő, majd edge (`FallbackSTT`)
  - TTS: Piper (hu_HU-anonymous-medium, pitch-tuned younger)
  - VAD: detect end-of-speech
Interfaces + stubs only.
"""

from __future__ import annotations

import array
import collections
import io
import json
import logging
import math
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol


def find_voice_binary(nev: str) -> str | None:
    """A hang-bináris teljes útvonala: előbb a PROJEKT VENV-je, aztán a PATH.

    A `piper` a `uv sync --extra tts`-ből jön, tehát a `.venv/bin`-be kerül — és az
    NINCS a PATH-on, amikor a systemd a `{venv}/bin/freedroid`-ot indítja: a
    szolgáltatás nem aktiválja a venv-et, csak a benne lévő futtathatót hívja. Kézzel,
    `uv run` alatt működne (az beteszi a venv-et a PATH-ba), tehát a hiba pont a
    FEJLESZTÉS alatt láthatatlan, és először a szolgáltatásként futó roboton jönne elő.

    Ugyanez a keresés szolgálja ki a health-checket is (`check_voice_binaries`) —
    egyetlen szabály, nem kettő, ami elcsúszhat.
    """
    venvben = Path(sys.executable).parent / nev
    if venvben.exists():
        return str(venvben)
    return shutil.which(nev)

if TYPE_CHECKING:
    from freedroid.config.settings import Settings

log = logging.getLogger(__name__)


class WakeWord(Protocol):
    def wait_for_wake(self) -> None:
        """Block until the 'Szabi' wake word is detected."""
        ...


class STT(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


class TTS(Protocol):
    def speak(self, text: str) -> None: ...


class VAD(Protocol):
    def record_until_silence(self) -> bytes:
        """Record from the USB mic until the speaker stops."""
        ...


class OpenWakeWord:
    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.2: train + integrate 'Szabi' wake word")

    def wait_for_wake(self) -> None:
        raise NotImplementedError


def rms(pcm: bytes) -> float:
    """16 bites mono PCM effektív értéke.

    Saját implementáció, mert az `audioop` a Python 3.13-ból KI LETT VÉVE (PEP 594) —
    a Pi pedig 3.13-on fut. Egy 50 ms-os darab 800 minta, tehát a költsége elhanyagolható.
    """
    if not pcm:
        return 0.0
    minta = array.array("h")
    # Páratlan bájt = fél minta: az `array` ilyenkor kivételt dob. A felvétel VÉGÉN ez
    # előfordulhat (a folyam félbevágva zárul), és egy hangfelvétel utolsó fél mintája
    # miatt nem szabad elveszíteni az egész mondatot.
    minta.frombytes(pcm[:len(pcm) // 2 * 2])
    # EGYETLEN bájtnál a `not pcm` még hamis, a csonkítás után viszont NULLA minta marad
    # -> ZeroDivisionError (PR #95 review, igazolva). A folyam vége pontosan így zárulhat.
    if not minta:
        return 0.0
    return math.sqrt(sum(x * x for x in minta) / len(minta))


def wav_bajtok(pcm: bytes, rate: int) -> bytes:
    """Nyers 16 bites mono PCM -> WAV, memóriában.

    Egy helyen, mert MINDKÉT STT-ág ugyanazt a fejlécet kívánja: a `whisper-cli` fájlt
    olvas, a `whisper-server` feltöltést vár. Két külön fejléc-építés némán elcsúszhatna
    (más ráta, más csatornaszám), és az eredmény nem hiba lenne, hanem ZAGYVA ÁTIRAT.
    """
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as ki:
        ki.setnchannels(1)
        ki.setsampwidth(2)
        ki.setframerate(rate)
        ki.writeframes(pcm)
    return puffer.getvalue()


def multipart(mezok: dict[str, str], fajl_nev: str, fajl: bytes) -> tuple[bytes, str]:
    """(törzs, Content-Type) egy multipart/form-data kéréshez, a szabvány könyvtárból.

    Kézzel, mert a projektnek nincs HTTP-kliens függősége, és EGY feltöltésért nem
    veszünk fel egyet: a `health.probe` is `urllib`-et használ. A határoló véletlen
    (`uuid4`), tehát nem fordulhat elő a hangban.
    """
    hatarolo = f"----freedroid-{uuid.uuid4().hex}"
    darabok = []
    for nev, ertek in mezok.items():
        darabok.append(
            f"--{hatarolo}\r\nContent-Disposition: form-data; name=\"{nev}\"\r\n\r\n"
            f"{ertek}\r\n".encode())
    darabok.append(
        f"--{hatarolo}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{fajl_nev}\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
    darabok.append(fajl)
    darabok.append(f"\r\n--{hatarolo}--\r\n".encode())
    return b"".join(darabok), f"multipart/form-data; boundary={hatarolo}"


class CloudWhisperSTT:
    """whisper.cpp SZERVER a felhőben (GPU), a WireGuard-alagúton át.

    A szerződés a rögzített commit FORRÁSÁBÓL van ellenőrizve (`examples/server`):
    `POST /inference`, multipart `file` + `language` + `prompt` + `response_format`,
    a válasz `{"text": ...}`. Ugyanaz a szótár-prompt megy, mint a helyi ágon — az
    nem finomhangolás, hanem MŰKÖDÉSI FELTÉTEL (a "Yotengrit" egyetlen modell
    szótárában sincs benne).
    """

    def __init__(self, settings: Settings | None = None,
                 opener: Callable[[urllib.request.Request, float], bytes] | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        self._opener = opener or _urlopen_bytes

    def elerheto(self) -> tuple[bool, str]:
        """(él-e a szerver, INDOK). Az indok azért kell, mert a naplóban a "miért az
        edge felelt?" kérdés csak így válaszolható meg utólag — ugyanaz az elv, mint a
        `FallbackLLMClient._probe`-nál."""
        url = self._cfg.stt_cloud_url
        try:
            self._opener(urllib.request.Request(url, method="GET"),
                         self._cfg.stt_cloud_probe_timeout_s)
        except Exception as e:  # noqa: BLE001 — bármilyen hiba = nem elérhető
            return False, f"nem elérhető ({url}: {type(e).__name__})"
        return True, "elérhető"

    def transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""
        mezok = {"language": self._cfg.stt_language, "response_format": "json",
                 "temperature": "0.0"}
        if self._cfg.stt_prompt:
            mezok["prompt"] = self._cfg.stt_prompt
        torzs, tipus = multipart(mezok, "felvetel.wav",
                                 wav_bajtok(audio, self._cfg.stt_sample_rate))
        keres = urllib.request.Request(f"{self._cfg.stt_cloud_url}/inference",
                                       data=torzs, method="POST",
                                       headers={"Content-Type": tipus})
        try:
            nyers = self._opener(keres, self._cfg.stt_cloud_timeout_s)
        except Exception as e:  # noqa: BLE001 — hálózat/HTTP/időtúllépés, mind ugyanaz
            raise RuntimeError(f"a felhős STT nem válaszolt: {type(e).__name__}: {e}") from e
        try:
            return str(json.loads(nyers)["text"]).strip()
        except (ValueError, KeyError, TypeError) as e:
            # NEM nyeljük el: egy váratlan válaszformátum ÜRES átiratként úgy nézne ki,
            # mintha a felhasználó nem mondott volna semmit — a robot csak hallgatna.
            raise RuntimeError(
                f"a felhős STT válasza értelmezhetetlen: {nyers[:120]!r}") from e


def _urlopen_bytes(keres: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(keres, timeout=timeout) as valasz:  # noqa: S310
        return valasz.read()


class FallbackSTT:
    """Felhő -> edge visszaesés, ugyanaz a létra, ami az LLM-nél már működik.

    A döntés MONDATONKÉNT újra megtörténik: az alagút a demó közben is felállhat vagy
    leeshet, és egy "egyszer edge, mindig edge" kliens a felállt alagutat sosem venné
    észre. A próba olcsó (egy GET), és pont azért van, hogy egy halott alagútnál ne
    160 KB hang feltöltése UTÁN derüljön ki a baj.

    A felhő hibája NEM buktatja a mondatot: leesünk az edge-re, és a `dontes()` őrzi meg,
    hogy miért. Némán viszont nem esünk le — a napló mindig megmondja, melyik ág felelt.
    """

    def __init__(self, settings: Settings | None = None,
                 felho: STT | None = None, edge: STT | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        self._beallitas = settings
        self._felho = felho
        self._edge = edge
        self._indok = ""
        self.utolso_agy = ""

    @property
    def felho(self) -> CloudWhisperSTT:
        if self._felho is None:
            self._felho = CloudWhisperSTT(self._beallitas)
        return self._felho

    @property
    def edge(self) -> WhisperCppSTT:
        # LUSTÁN: a helyi ág konstruktora binárist és modellt keres, és ha a felhő
        # felel, arra nincs is szükség. Egy hiányzó `whisper-cli` így nem akadályozza
        # meg a felhős működést.
        if self._edge is None:
            self._edge = WhisperCppSTT(self._beallitas)
        return self._edge

    def dontes(self) -> str:
        """MIÉRT az az ág felelt, ami. Teljes döntési nyom, egy sorban."""
        return self._indok

    def transcribe(self, audio: bytes) -> str:
        if self._cfg.stt_prefer_cloud:
            elerheto, indok = self.felho.elerheto()
            if elerheto:
                try:
                    szoveg = self.felho.transcribe(audio)
                    self._indok, self.utolso_agy = "cloud: felelt", "cloud"
                    return szoveg
                except RuntimeError as e:
                    indok = f"hibázott ({e})"
            self._indok = f"cloud: {indok} -> edge"
        else:
            self._indok = "cloud: kikapcsolva (stt_prefer_cloud=false) -> edge"
        log.info("STT: %s", self._indok)
        self.utolso_agy = "edge"
        return self.edge.transcribe(audio)


class WhisperCppSTT:
    """whisper.cpp-alapú átirat (Pi-n, offline).

    A `transcribe` NYERS PCM-et vár (16 bites, mono, `stt_sample_rate`), mert a VAD is
    azt ad — a WAV-fejlécet itt tesszük rá, mert a `whisper-cli` fájlt olvas.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        self._model = str(Path(self._cfg.whisper_model).expanduser())
        self._binaris = self._binaris_utvonal(self._cfg.whisper_binary)

    @staticmethod
    def _binaris_utvonal(beallitas: str) -> str:
        """Teljes útvonal -> az; puszta név -> a Piperrel KÖZÖS keresés (venv, majd PATH).

        A whisper.cpp forrásból fordul, tehát alapból egyik helyen sincs; de ha valaki
        telepíti, ne kelljen a configot átírnia."""
        utvonal = Path(beallitas).expanduser()
        if utvonal.parent != Path("."):
            return str(utvonal)
        return find_voice_binary(beallitas) or beallitas

    def transcribe(self, audio: bytes) -> str:
        """PCM -> magyar szöveg. Üres hangra üres sztring (nem hiba).

        Hiba esetén `RuntimeError`: az orchestrátor dönti el, mit kezd vele. Egy néma
        `except: pass` itt azt jelentené, hogy a robot nem válaszol, és semmi nem árulja
        el, miért — pont az a hibafajta, ami a színpadon lefagyásnak látszik.
        """
        if not audio:
            return ""
        if not Path(self._model).exists():
            raise RuntimeError(f"a whisper modell nem található: {self._model}")

        with tempfile.TemporaryDirectory() as konyvtar:
            wav = Path(konyvtar) / "felvetel.wav"
            wav.write_bytes(wav_bajtok(audio, self._cfg.stt_sample_rate))
            # Sorban épül, nem beszúrással: a korábbi `parancs[-2:-2]` a `-f` POZÍCIÓJÁRA
            # támaszkodott, tehát egy későbbi kapcsoló hozzáadása csendben rossz helyre
            # tette volna a promptot. (PR #95 review.)
            parancs = [self._binaris, "-m", self._model,
                       "-l", self._cfg.stt_language,
                       "-t", str(self._cfg.stt_threads),
                       "-nt"]                      # időbélyegek nélkül: csak a szöveg
            if self._cfg.stt_prompt:
                parancs += ["--prompt", self._cfg.stt_prompt]
            parancs += ["-f", str(wav)]
            try:
                kesz = subprocess.run(parancs, capture_output=True,
                                      timeout=self._cfg.stt_timeout_s, check=False)
            except OSError as e:
                raise RuntimeError(f"a `whisper-cli` nem indult el ({self._binaris}): {e}") from e
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"a whisper {self._cfg.stt_timeout_s} s alatt nem végzett") from e

        if kesz.returncode != 0:
            hiba = kesz.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(f"a whisper hibára futott ({kesz.returncode}): "
                               f"{hiba[-1] if hiba else 'nincs üzenet'}")
        return kesz.stdout.decode("utf-8", "replace").strip()


class EnergyVAD:
    """Beszédvég-detektálás a jel energiájából — felvétel a mondat végéig.

    A küszöb NEM beégetett szám: a felvétel elején megmérjük a tényleges zajszintet, és
    ahhoz képest szorzunk. Egy fix érték a konferencia-teremben (zajos) és a szobában
    (csendes) nem lehet ugyanaz, a demó pedig a zajos helyen lesz.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        self._darab_s = 0.05
        # Bájtban: 16 bites mono, tehát mintánként 2 bájt.
        self._darab = int(self._cfg.stt_sample_rate * self._darab_s) * 2
        # Az UTOLSÓ felvétel mért értékei. Diagnosztika: a "nem hallottam semmit" magában
        # nem mond semmit — e nélkül nem lehet eldönteni, hogy túl magas a küszöb, vagy
        # tényleg csend volt. A hívó ezeket kiírja.
        self.zajszint = 0.0
        self.kuszob = 0.0

    def _darabszam(self, masodperc: float) -> int:
        """Másodperc -> hány 50 ms-os darab. `round`, NEM `int`.

        Az `int()` lefelé csonkít, és a lebegőpontos osztás pont a kerek értékeknél
        téved alá: `0.3 / 0.05 = 5.999999999999999` -> 5 darab 6 helyett, `15 / 0.05
        = 299.99999999999994` -> 299 darab 300 helyett. Minden időzítés NÉMÁN egy
        darabbal rövidebb lett volna — az elő-roll levágná a szó elejét, a maximális
        hossz pedig hamarabb vágna. Egy önmagát bizonyító teszt fogta meg.
        """
        return round(masodperc / self._darab_s)

    def record_until_silence(self) -> bytes:
        parancs = shlex.split(self._cfg.record_command.format(
            rate=self._cfg.stt_sample_rate))
        try:
            felvevo = subprocess.Popen(parancs, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        except OSError as e:
            raise RuntimeError(f"a felvevő nem indult el ({parancs[0]}): {e}") from e
        try:
            return self._felvesz(felvevo)
        finally:
            felvevo.kill()
            felvevo.wait()

    def _olvas_darab(self, felvevo) -> bytes:
        darab = felvevo.stdout.read(self._darab)
        if not darab:
            hiba = (felvevo.stderr.read() or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"a felvétel megszakadt: {hiba or 'a felvevő kilépett'}")
        return darab

    def _felvesz(self, felvevo) -> bytes:
        cfg = self._cfg
        # 1. zajszint: ebből lesz a küszöb.
        #
        # MINIMUM, nem átlag — MÉRVE 2026-08-25, és ez a különbség tette használhatatlanná
        # az első változatot. A mérőablak a felvétel ELEJÉN van; ha a beszélő azonnal
        # megszólal (márpecig ENTER után azt teszi), az átlagba BELESZÁMÍT a saját hangja,
        # és a küszöb ANNAK a háromszorosa lesz. Ilyenkor a normál beszéd sosem lépi át —
        # csak a kiabálás. A minimum a mérőablak legcsendesebb darabját veszi, tehát a
        # beleló beszéd nem fújja fel; a `vad_min_rms` pedig alulról fog egy néma
        # mikrofont (aminél a szorzó 0-t adna).
        zaj = [rms(self._olvas_darab(felvevo))
               for _ in range(max(1, self._darabszam(cfg.vad_calib_s)))]
        self.zajszint = min(zaj)
        self.kuszob = max(self.zajszint * cfg.vad_snr, cfg.vad_min_rms)
        log.debug("VAD: zajszint %.0f (átlag %.0f), küszöb %.0f",
                  self.zajszint, sum(zaj) / len(zaj), self.kuszob)
        kuszob = self.kuszob

        # 2. várunk a beszéd KEZDETÉRE. Közben gyűrűben tartjuk az utolsó néhány
        # darabot: e nélkül a mondat első hangja LEVÁGVA kerülne a Whisperhez, mert a
        # küszöböt már a szó közepén lépjük át. Egy levágott "Szabi" felismerhetetlen.
        # `max(1, ...)` NÉLKÜL: a config engedi a 0-t, és akkor a 0 tényleg nullát
        # jelentsen (a `max(1, ...)` egy darabot mindig megtartott — a szerződés és a
        # kód nem egyezett).
        eloroll = collections.deque(maxlen=self._darabszam(cfg.vad_preroll_s))
        hatarido = time.monotonic() + cfg.vad_start_timeout_s
        while True:
            darab = self._olvas_darab(felvevo)
            if rms(darab) >= kuszob:
                break
            eloroll.append(darab)
            if time.monotonic() > hatarido:
                return b""      # nem szólalt meg senki — NEM hiba, csak nincs mondat

        # 3. felvétel a csend beálltáig
        felvett = [*eloroll, darab]
        csend_darab = 0
        kell_csend = max(1, self._darabszam(cfg.vad_silence_s))
        max_darab = self._darabszam(cfg.vad_max_s)
        while len(felvett) < max_darab:
            darab = self._olvas_darab(felvevo)
            felvett.append(darab)
            csend_darab = 0 if rms(darab) >= kuszob else csend_darab + 1
            if csend_darab >= kell_csend:
                break
        return b"".join(felvett)


class PiperTTS:
    """Piper TTS: szöveg -> nyers audio -> lejátszás. Offline, a Pi-n (szuverenitás).

    A `piper` BINÁRIST hívjuk, nem a Python API-t: a health-check is a binárist keresi
    (`which piper`), tehát egy út marad ellenőrizve.

    A két folyamat CSŐVEL van összekötve (`--output-raw | aplay`), nem ideiglenes
    WAV-fájlon át. Ez nem teljesítmény-kérdés: a demó előtti posztúra szerint a gépen
    NEM tárolunk elhangzott mondatot, egy `/tmp`-be írt hangfájl pedig pontosan az lenne.

    A kapcsolók MÉRVE, nem a dokumentációból: `piper --help` + három valódi futtatás
    (2026-08-18). A `--output-raw` 16 bites, mono, a modell mintavételi frekvenciáján —
    ezért kell a rátát a modell mellől kiolvasni, és nem beégetni.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        # `expanduser`: a config `~`-t ír (a modell a robot-user home-jában van), és a
        # subprocess NEM oldja fel a tildét — shell nélkül futunk, nincs, ami kibontsa.
        self._model = str(Path(self._cfg.piper_model).expanduser())
        # A FUTÓ folyamatok, hogy az `abort()` MÁS SZÁLRÓL is elérje őket. A zár nem
        # díszítés: az `abort()` a trigger szálán fut, a `speak()` a főszálon.
        self._folyamatok: tuple | None = None
        self._zar = threading.Lock()
        self._megszakitva = threading.Event()

    def sample_rate(self) -> int:
        """A modell mintavételi frekvenciája, a MELLETTE lévő configból.

        Nem beégetett 22050: az a `medium` szint értéke, a `low`/`high` hangoké más.
        Egy rossz ráta nem hibát ad, hanem TORZ, gyorsított vagy lassított beszédet —
        némán. Ezért olvassuk ki.
        """
        config = Path(self._model + ".onnx.json")
        try:
            return int(json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except (OSError, KeyError, ValueError) as e:
            raise RuntimeError(
                f"a Piper hang configja nem olvasható ({config}): {e} — a hang KÉT "
                f"fájlból áll (.onnx + .onnx.json), és mindkettő kell") from e

    @staticmethod
    def _olvas(nev: str, folyam, ide: dict) -> None:
        """Egy stderr teljes kiolvasása, saját szálon. Sosem dob: egy hibaüzenet
        olvasása közben keletkező hiba nem buktathatja meg magát a beszédet."""
        try:
            ide[nev] = folyam.read()
        except Exception:  # noqa: BLE001 — a diagnosztika sosem fontosabb a működésnél
            ide[nev] = b""

    def abort(self) -> None:
        """A FOLYAMATBAN LÉVŐ beszéd azonnali megszakítása, más szálról.

        A megszakítás NEM HIBA: a `speak()` csendben tér vissza utána, nem dob. Enélkül
        minden "állj" gombnyomás egy `RuntimeError`-t adna a hurokban ("lejátszás hiba
        (-9)"), és a napló tele lenne álhibákkal — pont azt rejtve el, ha egyszer VALÓDI
        lejátszási hiba jön.

        Beszéd nélkül is hívható (nincs mit megszakítani): a jelzőt akkor is beállítja,
        így egy épp INDULÓ mondat sem csúszik át a résen.
        """
        self._megszakitva.set()
        with self._zar:
            folyamatok = self._folyamatok
        for folyamat in folyamatok or ():
            try:
                folyamat.kill()
            except Exception:  # noqa: BLE001 — a másikat is ki kell lőni
                log.exception("a beszéd megszakítása elhasalt: %r", folyamat)

    def speak(self, text: str) -> None:
        """Kimondja a szöveget. Üres szövegre nem csinál semmit (nem hiba).

        Hiba esetén `RuntimeError` — a hívó (orchestrátor) dönti el, elnyeli-e. Egy néma
        `except: pass` itt azt jelentené, hogy a robot a színpadon csendben marad, és
        semmi nem árulja el, miért.
        """
        if not (text := text.strip()):
            return

        # ELŐBB töröljük a jelzőt: egy KORÁBBI mondat megszakítása nem némíthatja el a
        # következőt. (A gomb megnyomása és az új mondat indulása között a jelző áll.)
        self._megszakitva.clear()

        gen_parancs = [find_voice_binary("piper") or "piper",
                       "--model", self._model + ".onnx", "--output-raw",
                       "--length-scale", str(self._cfg.length_scale)]
        jatszo_parancs = shlex.split(self._cfg.play_command.format(rate=self.sample_rate()))

        try:
            gen = subprocess.Popen(gen_parancs, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise RuntimeError(f"a `piper` nem indult el: {e}") from e
        try:
            jatszo = subprocess.Popen(jatszo_parancs, stdin=gen.stdout,
                                      stderr=subprocess.PIPE)
        except OSError as e:
            # A csöveket EXPLICITEN zárjuk. A CPython refszámlálása általában elintézné,
            # de a kivétel-objektum életben tartja a keretet (és vele a `gen`-t), amíg a
            # traceback él — egy tartósan hibázó lejátszónál (pl. hiányzó `aplay`) ez
            # mondatonként három leíró, egy hosszan futó szolgáltatásban.
            for folyam in (gen.stdin, gen.stdout, gen.stderr):
                if folyam is not None:
                    folyam.close()
            gen.kill()
            gen.wait()
            raise RuntimeError(f"a lejátszó nem indult el ({jatszo_parancs[0]}): {e}") from e

        # Innentől megszakítható: az `abort()` más szálról ezt a két folyamatot lövi ki.
        # A nyilvántartásba vétel a MÁSODIK Popen után van, hogy félig felépült állapotot
        # ne adjunk ki — de MÉG az írás/várakozás előtt, tehát nincs olyan pillanat,
        # amikor a robot beszél, de nem lehet elhallgattatni.
        with self._zar:
            self._folyamatok = (gen, jatszo)
        # És ha az `abort()` PONT a két lépés között futott le, azt itt kapjuk el: a
        # jelző már áll, tehát a most induló mondatot azonnal el is vágjuk. Enélkül a
        # gombnyomás átcsúszna a résen, és a robot mégis megszólalna.
        if self._megszakitva.is_set():
            for folyamat in (gen, jatszo):
                folyamat.kill()

        # A SZÜLŐNEK el kell engednie a cső olvasó végét, különben az `aplay` sosem lát
        # EOF-ot, és a beszéd végén örökre várna. Ez a klasszikus cső-holtpont.
        gen.stdout.close()

        # MINDKÉT stderr-t PÁRHUZAMOSAN olvassuk. Sorban olvasva ez holtpontba futhat:
        # ha a lejátszó megáll (foglalt hangeszköz), a `piper` a megtelt csőre írva
        # blokkol, tehát az ő stderr-je sosem ér EOF-ot — és a lejátszó hibaüzenetéhez,
        # ami épp megmagyarázná az egészet, sosem jutnánk el. (PR #91 review.)
        hibak: dict[str, bytes] = {}
        szalak = [threading.Thread(target=self._olvas, args=(nev, folyam, hibak),
                                   daemon=True)
                  for nev, folyam in (("piper", gen.stderr), ("lejátszó", jatszo.stderr))]
        for szal in szalak:
            szal.start()

        # A `piper` AZONNAL kiléphet (rossz modell-útvonal, hibás kapcsoló), és akkor az
        # írás `BrokenPipeError`-t dob. Elnyeljük — nem azért, mert nem érdekes, hanem
        # mert az ÉRDEKES üzenet a piper stderr-jén van, és azt pár sorral lejjebb
        # ki is olvassuk. A nyers BrokenPipeError csak elrejtené a valódi okot.
        try:
            gen.stdin.write(text.encode("utf-8"))
            gen.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        # ÉS IDŐKORLÁT. A szálas olvasás önmagában NEM elég — a review javaslata itt
        # megáll félúton: ha a lejátszó beragad a hangeszköz megnyitásán anélkül, hogy
        # kilépne, a `piper` örökre blokkol az írásnál, az ő stderr-je sosem ér EOF-ot,
        # és a `join()` ugyanúgy örökre vár. Csak a szálak mellett a robot NÉMÁN,
        # határidő nélkül állna meg a színpadon — a legrosszabb kimenet.
        # KÖZÖS határidő, nem két külön időkorlát. Egymás után, teljes értékkel hívva a
        # legrosszabb eset a KÉTSZERESE lett volna — vagyis a `speak_timeout_s` nem azt
        # jelentette volna, amit a neve és a dokumentációja ígér. (PR #91 review.)
        hatarido = self._cfg.speak_timeout_s
        vege = time.monotonic() + hatarido
        try:
            gen.wait(timeout=max(0.0, vege - time.monotonic()))
            jatszo.wait(timeout=max(0.0, vege - time.monotonic()))
        except subprocess.TimeoutExpired as e:
            for folyamat in (gen, jatszo):
                folyamat.kill()
                folyamat.wait()
            for szal in szalak:
                szal.join(timeout=1.0)
            # A nyilvántartást a HIBAÁGON is ürítjük: különben egy beragadt mondat után
            # az `abort()` halott folyamatokra hivatkozna, és a jelző a KÖVETKEZŐ
            # mondatot vágná el.
            with self._zar:
                self._folyamatok = None
            raise RuntimeError(f"a beszéd beragadt ({hatarido:g} s) és leállítottuk: {e} "
                               f"— foglalt vagy hibás hangeszköz?") from e
        for szal in szalak:
            szal.join(timeout=1.0)

        with self._zar:
            self._folyamatok = None

        # MEGSZAKÍTÁS != HIBA. A kilőtt folyamat -9-cel tér vissza; azt hibaként jelenteni
        # azt jelentené, hogy minden "állj" gombnyomás egy kivételt szül a hurokban.
        if self._megszakitva.is_set():
            log.info("a beszéd megszakítva (állj)")
            return

        gen_hiba = hibak.get("piper", b"").decode("utf-8", "replace")
        jatszo_hiba = hibak.get("lejátszó", b"").decode("utf-8", "replace")

        if gen.returncode:
            raise RuntimeError(f"piper hiba ({gen.returncode}): {gen_hiba.strip()[:300]}")
        if jatszo.returncode:
            raise RuntimeError(f"lejátszás hiba ({jatszo.returncode}): "
                               f"{jatszo_hiba.strip()[:300]}")
