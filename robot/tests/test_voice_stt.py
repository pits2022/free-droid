"""STT + VAD — ami mikrofon és whisper.cpp NÉLKÜL is elromolhat.

A felismerés minőségét csak a Pi-n lehet megítélni; itt az van, ami e nélkül is
eltörik: az energia-számítás, a VAD állapotgépe (elő-roll, csendszámlálás,
időkorlátok) és a whisper-parancs alakja.
"""

from __future__ import annotations

import array
import dataclasses
import math

import pytest

from freedroid.config.settings import Settings, VoiceSettings
from freedroid.voice import EnergyVAD, WhisperCppSTT, rms

RATE = 16000
DARAB_S = 0.05
MINTA_DARAB = int(RATE * DARAB_S)          # 800 minta = 1600 bájt


def pcm(amplitudo: int, darabok: int = 1) -> bytes:
    """`darabok` darab 50 ms-os blokk, adott amplitúdóval (négyszögjel)."""
    return array.array("h", [amplitudo] * (MINTA_DARAB * darabok)).tobytes()


def beallitas(**kw) -> Settings:
    return dataclasses.replace(Settings(), voice=VoiceSettings(**kw))


# --- energia -----------------------------------------------------------------------

def test_a_csend_nulla_a_jel_nem():
    assert rms(pcm(0)) == 0.0
    assert rms(pcm(1000)) == pytest.approx(1000.0)


def test_az_ures_bemenet_nem_hasal_el():
    """A felvétel legelején nulla bájt is jöhet — ne nullával osszunk."""
    assert rms(b"") == 0.0


def test_a_PARATLAN_bajt_nem_viszi_el_a_felvetelt():
    """Egy félbevágott folyam utolsó fél mintája miatt nem szabad elveszíteni a mondatot.

    (Az `array.frombytes` páratlan hosszra ValueError-t dob — ezért a csonkítás.)
    """
    assert rms(pcm(1000) + b"\x01") == pytest.approx(1000.0)


def test_az_audioop_hianyat_potoljuk():
    """A Pi Python 3.13-on fut, ahonnan az `audioop` KI LETT VÉVE (PEP 594).
    Az érték ugyanaz kell legyen, mint a kézzel számolt effektív érték."""
    minta = array.array("h", [100, -200, 300, -400])
    varhato = math.sqrt(sum(x * x for x in minta) / len(minta))
    assert rms(minta.tobytes()) == pytest.approx(varhato)


# --- VAD állapotgép ----------------------------------------------------------------

class AlFelvevo:
    """`arecord` helyett: előre megírt darabokat ad vissza, majd EOF-ot."""

    def __init__(self, darabok: list[bytes]):
        self._darabok = list(darabok)
        self.stdout = self
        self.stderr = _Ures()
        self.olvasasok = 0

    def read(self, n: int = -1) -> bytes:
        self.olvasasok += 1
        return self._darabok.pop(0) if self._darabok else b""

    def kill(self) -> None:
        return None

    def wait(self, timeout=None):
        return 0


class _Ures:
    def read(self, n: int = -1) -> bytes:
        return b""


def vad_futtat(darabok: list[bytes], monkeypatch, **kw) -> bytes:
    from freedroid import voice

    felvevo = AlFelvevo(darabok)
    monkeypatch.setattr(voice.subprocess, "Popen", lambda *a, **k: felvevo)
    return EnergyVAD(beallitas(**kw)).record_until_silence()


def test_a_kuszob_a_MERT_zajszinthez_igazodik(monkeypatch):
    """Egy fix küszöb a zajos teremben és a csendes szobában nem lehet ugyanaz — a
    demó pedig a zajos helyen lesz. Itt a zaj 400, tehát a 3x-os szorzóval 1200 a
    küszöb: az 500-as "beszéd" NEM indítaná el a felvételt, a 3000-es igen."""
    kalib = [pcm(400)] * 6          # 0,3 s zajszint-mérés
    halk = [pcm(500)] * 4           # a zaj fölött van, de a küszöb alatt
    hangos = [pcm(3000)] * 2
    csend = [pcm(0)] * 20
    felvett = vad_futtat(kalib + halk + hangos + csend, monkeypatch,
                         vad_min_rms=1.0, vad_snr=3.0)
    # A halk rész csak elő-rollként kerülhet be, a hangos mindenképp:
    assert len(felvett) > 0
    assert rms(felvett) > 500


def test_az_ELO_ROLL_megorzi_a_szo_elejet(monkeypatch):
    """A küszöböt már a szó KÖZEPÉN lépjük át, tehát elő-roll nélkül a mondat első
    hangja levágva menne a Whisperhez — egy levágott "Szabi" felismerhetetlen."""
    darabok = [pcm(10)] * 6 + [pcm(20)] * 6 + [pcm(5000)] * 2 + [pcm(0)] * 20
    kozos = dict(vad_min_rms=1000.0, vad_silence_s=0.25)
    vele = vad_futtat(darabok, monkeypatch, vad_preroll_s=0.3, **kozos)
    nelkule = vad_futtat(darabok, monkeypatch, vad_preroll_s=0.0, **kozos)
    # A teszt ÖNMAGÁT bizonyítja: a különbség pontosan a 0,3 s elő-roll (6 darab).
    assert len(vele) - len(nelkule) == 6 * MINTA_DARAB * 2


def test_a_csend_zarja_a_mondatot_nem_a_maximum(monkeypatch):
    kalib = [pcm(10)] * 6
    beszed = [pcm(5000)] * 4
    csend = [pcm(0)] * 40
    felvett = vad_futtat(kalib + beszed + csend, monkeypatch,
                         vad_min_rms=1000.0, vad_preroll_s=0.0,
                         vad_silence_s=0.25, vad_max_s=15.0)
    # 4 beszéd + 5 csend-darab (0,25 s), nem a teljes 40 csend-darab.
    assert len(felvett) < len(b"".join(beszed + csend))


def test_a_NEMA_mikrofon_ures_hangot_ad_nem_hibat(monkeypatch):
    """Ha senki nem szólal meg, az nem hiba: nincs mondat. Egy kivétel itt a
    `run()` hurkot állítaná meg minden csendes körben."""
    kalib = [pcm(10)] * 6
    assert vad_futtat(kalib + [pcm(10)] * 200, monkeypatch,
                      vad_min_rms=1000.0, vad_start_timeout_s=0.001) == b""


def test_a_megszakadt_felvetel_HANGOS(monkeypatch):
    """EOF a felvevőtől = a mikrofon eltűnt. Ez ELLENTÉTBEN a csenddel valódi hiba."""
    with pytest.raises(RuntimeError, match="megszakadt"):
        vad_futtat([], monkeypatch)


# --- whisper-parancs ---------------------------------------------------------------

def test_a_SZOTAR_PROMPT_bekerul_a_parancsba(tmp_path, monkeypatch):
    """MÉRVE 2026-08-25: prompt nélkül a "Yotengrit" -> "tenvrít". A robot
    legfontosabb fogalma. Ha a prompt kiesne a parancsból, a hiba NÉMA lenne:
    a felismerés csak rosszabb lenne, nem hibás."""
    from freedroid import voice

    modell = tmp_path / "m.bin"
    modell.write_bytes(b"x")
    parancsok: list[list[str]] = []

    class Kesz:
        returncode = 0
        stdout = b" Jo napot, Teremto.\n"
        stderr = b""

    monkeypatch.setattr(voice.subprocess, "run",
                        lambda p, **k: (parancsok.append(p), Kesz())[1])
    stt = WhisperCppSTT(beallitas(whisper_model=str(modell),
                                  stt_prompt="Szabi, Yotengrit."))
    assert stt.transcribe(pcm(1000)) == "Jo napot, Teremto."
    assert "--prompt" in parancsok[0]
    assert "Szabi, Yotengrit." in parancsok[0]
    # a `-f` és a fájl VÉGIG a parancs végén marad
    assert parancsok[0][-2] == "-f"


def test_ures_hangra_nem_indul_whisper(tmp_path, monkeypatch):
    from freedroid import voice

    def tilos(*a, **k):
        raise AssertionError("üres hangra nem szabad folyamatot indítani")
    monkeypatch.setattr(voice.subprocess, "run", tilos)
    assert WhisperCppSTT(beallitas()).transcribe(b"") == ""


def test_a_hianyzo_modell_HANGOS(tmp_path):
    stt = WhisperCppSTT(beallitas(whisper_model=str(tmp_path / "nincs.bin")))
    with pytest.raises(RuntimeError, match="nem található"):
        stt.transcribe(pcm(1000))


def test_a_BELELOGO_beszed_nem_fujja_fel_a_kuszobot(monkeypatch):
    """MÉRVE 2026-08-25, és ez tette használhatatlanná az első változatot.

    A zajszint-mérés a felvétel ELEJÉN van. Ha a beszélő azonnal megszólal (ENTER után
    azt teszi), ÁTLAGgal a küszöb a saját hangja háromszorosa lesz — a normál beszéd
    sosem lépi át, csak a kiabálás. MINIMUMmal a mérőablak legcsendesebb darabja számít.

    Itt a mérőablak fele csend (100), fele beszéd (5000):
      átlaggal:  (100+5000)/2 * 3 = 7650  -> a 3000-es beszédet NEM hallaná meg
      minimummal: 100 * 3        =  300  -> meghallja
    """
    kalib = [pcm(100)] * 3 + [pcm(5000)] * 3
    beszed = [pcm(3000)] * 2
    csend = [pcm(0)] * 20
    felvett = vad_futtat(kalib + beszed + csend, monkeypatch,
                         vad_min_rms=1.0, vad_snr=3.0, vad_preroll_s=0.0)
    assert felvett, "a normál hangerőt is meg kell hallania"


def test_az_EGYETLEN_bajt_sem_hasal_el():
    """PR #95 review, igazolva: a `not pcm` egy bájtra még hamis, a fél minta
    csonkítása után viszont NULLA minta marad -> ZeroDivisionError. A felvételi folyam
    vége pontosan így zárulhat, és a kivétel a `run()` hurkot vinné el."""
    assert rms(b"\x01") == 0.0


# --- FELHŐS STT: a kliens és a visszaesés, hálózat nélkül -------------------------

class AlNyito:
    """A HTTP-réteg helyettese. Rögzíti a kéréseket, és megjátszott választ ad.

    Nem `urllib`-et foltozunk, hanem a beadott `opener`-t cseréljük: így a teszt
    pontosan azt méri, amit a kliens ÖSSZEÁLLÍT, nem azt, hogy a szabvány könyvtár
    működik-e.
    """

    def __init__(self, valasz: bytes = b'{"text": "szia Teremto"}', hiba: Exception | None = None):
        self.valasz, self.hiba = valasz, hiba
        self.keresek: list[tuple[str, str, bytes | None, float]] = []

    def __call__(self, keres, timeout):
        self.keresek.append((keres.method, keres.full_url, keres.data, timeout))
        if self.hiba is not None:
            raise self.hiba
        return self.valasz


def test_a_multipart_torzs_a_hangot_VALTOZATLANUL_viszi():
    """A hang bináris: egy téves kódolás/escape-elés nem hibát adna, hanem ZAGYVA
    átiratot — azaz pont úgy nézne ki, mint egy rossz mikrofon."""
    from freedroid.voice import multipart

    hang = bytes(range(256))
    torzs, tipus = multipart({"language": "hu"}, "felvetel.wav", hang)
    hatarolo = tipus.split("boundary=")[1]
    assert hang in torzs
    assert torzs.startswith(f"--{hatarolo}\r\n".encode())
    assert torzs.endswith(f"\r\n--{hatarolo}--\r\n".encode())
    assert b'name="language"' in torzs and b"\r\n\r\nhu\r\n" in torzs
    assert b'name="file"; filename="felvetel.wav"' in torzs


def test_a_wav_fejlec_a_BEALLITOTT_ratat_viszi():
    """Mindkét STT-ág ugyanezt a fejlécet kapja. A Whisper KÖTÖTTEN 16 kHz monót vár,
    és rossz rátára nem hibázik, hanem rosszul ért (mérve 2026-08-26)."""
    import io
    import wave

    from freedroid.voice import wav_bajtok

    with wave.open(io.BytesIO(wav_bajtok(pcm(1000, 2), RATE))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        assert w.getnframes() == MINTA_DARAB * 2


def test_a_felhos_keres_a_SZOTAR_PROMPTOT_is_viszi():
    """A prompt nélkül a "Yotengrit" -> "TENVRÍT" (mérve). A felhős ág ugyanazt a
    működési feltételt kívánja, mint a helyi — két külön parancsépítés itt csendben
    szétcsúszhatna."""
    from freedroid.voice import CloudWhisperSTT

    nyito = AlNyito()
    szoveg = CloudWhisperSTT(beallitas(stt_prompt="Szabi, Yotengrit."), opener=nyito).transcribe(pcm(1000))
    assert szoveg == "szia Teremto"
    modszer, url, torzs, timeout = nyito.keresek[0]
    assert (modszer, url) == ("POST", "http://10.0.0.1:8080/inference")
    assert b"Szabi, Yotengrit." in torzs and b'name="language"' in torzs
    assert b"\r\n\r\nhu\r\n" in torzs
    assert timeout == VoiceSettings().stt_cloud_timeout_s


def test_ures_hangra_NEM_indul_halozati_keres():
    from freedroid.voice import CloudWhisperSTT

    nyito = AlNyito()
    assert CloudWhisperSTT(beallitas(), opener=nyito).transcribe(b"") == ""
    assert nyito.keresek == []


def test_az_ERTELMEZHETETLEN_valasz_HANGOS_hiba_nem_ures_atirat():
    """A legfontosabb hibaág: egy váratlan válaszformátum ÜRES átiratként úgy nézne ki,
    mintha a felhasználó nem mondott volna semmit — a robot csak hallgatna, és semmi
    nem árulná el, miért."""
    from freedroid.voice import CloudWhisperSTT

    with pytest.raises(RuntimeError, match="értelmezhetetlen"):
        CloudWhisperSTT(beallitas(), opener=AlNyito(valasz=b"<html>502</html>")).transcribe(pcm(1000))


class AlSTT:
    def __init__(self, valasz="edge szoveg"):
        self.valasz, self.hivasok = valasz, 0

    def transcribe(self, audio):
        self.hivasok += 1
        return self.valasz


def _felhos(nyito) -> object:
    from freedroid.voice import CloudWhisperSTT
    return CloudWhisperSTT(beallitas(), opener=nyito)


def test_elo_alagutnal_a_FELHO_felel():
    from freedroid.voice import FallbackSTT

    edge = AlSTT()
    stt = FallbackSTT(beallitas(), felho=_felhos(AlNyito()), edge=edge)
    assert stt.transcribe(pcm(1000)) == "szia Teremto"
    assert edge.hivasok == 0
    assert stt.utolso_agy == "cloud"


def test_halott_alagutnal_az_EDGE_felel_es_a_dontes_MEGMONDJA_miert():
    from freedroid.voice import FallbackSTT

    edge = AlSTT()
    stt = FallbackSTT(beallitas(), felho=_felhos(AlNyito(hiba=OSError("nincs útvonal"))),
                      edge=edge)
    assert stt.transcribe(pcm(1000)) == "edge szoveg"
    assert edge.hivasok == 1
    assert stt.utolso_agy == "edge"
    assert "nem elérhető" in stt.dontes(), stt.dontes()


def test_a_kikapcsolt_felho_MEG_NEM_IS_PROBALKOZIK():
    """`stt_prefer_cloud=false` a szuverén/offline demó kapcsolója: ilyenkor egyetlen
    csomag sem megy ki a gépből, nem csak a hang nem."""
    from freedroid.voice import FallbackSTT

    nyito, edge = AlNyito(), AlSTT()
    stt = FallbackSTT(beallitas(stt_prefer_cloud=False), felho=_felhos(nyito), edge=edge)
    assert stt.transcribe(pcm(1000)) == "edge szoveg"
    assert nyito.keresek == []
    assert "kikapcsolva" in stt.dontes()


def test_az_ELO_de_HIBAZO_felho_is_az_edge_re_esik():
    """Külön ág: a próba ÁTMEGY (a szerver felel), a munka mégis elhasal — pl. a GPU
    meghalt, vagy a modell nincs betöltve. Ha csak az elérhetőséget néznénk, a mondat
    itt elveszne, holott az edge ki tudná szolgálni."""
    from freedroid.voice import FallbackSTT

    class ProbaOkPostBukik(AlNyito):
        def __call__(self, keres, timeout):
            self.keresek.append((keres.method, keres.full_url, keres.data, timeout))
            if keres.method == "POST":
                raise OSError("a szerver bontotta a kapcsolatot")
            return b""

    edge = AlSTT()
    stt = FallbackSTT(beallitas(), felho=_felhos(ProbaOkPostBukik()), edge=edge)
    assert stt.transcribe(pcm(1000)) == "edge szoveg"
    assert edge.hivasok == 1
    assert "hibázott" in stt.dontes(), stt.dontes()
