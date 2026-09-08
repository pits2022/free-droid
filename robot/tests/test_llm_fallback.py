"""A felhő -> edge visszaesés (Phase 4.2).

A modul tétele nem az, hogy „HTTP-t hív", hanem hogy a HÁTTÉR-VÁLASZTÁS jó okokból
történik: a rövid próba dönt, a generálás hosszú korlátot kap, és a hidegindítás nem
tolja a robotot a gyengébb modellre.
"""

from __future__ import annotations

import pytest

from freedroid.llm import Backend, FallbackLLMClient, LLMUnavailable


class FakeOllama:
    """Egy Ollama-példány. `hiba` esetén minden hívása azzal bukik."""

    def __init__(self, host: str, timeout: float, valasz: str = "Igen, Teremtőm.",
                 hiba: Exception | None = None) -> None:
        self.host = host
        self.timeout = timeout
        self._valasz = valasz
        self._hiba = hiba
        self.hivasok: list[dict] = []

    def generate(self, **kw):
        self.hivasok.append(kw)
        if self._hiba is not None:
            raise self._hiba
        return {"response": self._valasz}


class Halo:
    """Az elérhetőség-próba és a kliensgyártás egy helyen, hogy a teszt mérni tudja."""

    def __init__(self, elerheto: set[str], **kw) -> None:
        self.elerheto = elerheto
        self.kw = kw
        self.peldanyok: list[FakeOllama] = []
        self.probak: list[str] = []

    def http_get(self, url: str, timeout: float = 4.0):
        self.probak.append(url)
        gep = url.split("/api/")[0]
        return (200 if gep in self.elerheto else 0), ""

    def gyar(self, host: str, timeout: float):
        p = FakeOllama(host, timeout, **self.kw.get(host, {}))
        self.peldanyok.append(p)
        return p


CLOUD = "http://10.0.0.1:11434"
EDGE = "http://127.0.0.1:11434"


def kliens(monkeypatch, halo: Halo) -> FallbackLLMClient:
    monkeypatch.setattr("freedroid.llm.http_get", halo.http_get)
    return FallbackLLMClient(client_factory=halo.gyar)


def test_a_felho_az_elsodleges(monkeypatch):
    halo = Halo({CLOUD, EDGE})
    c = kliens(monkeypatch, halo)
    assert c.generate("Ki vagy?") == "Igen, Teremtőm."
    assert c.active_backend() is Backend.CLOUD
    assert halo.peldanyok[0].host == CLOUD


def test_elerhetetlen_felho_eseten_az_edge_felel(monkeypatch):
    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    assert c.generate("Ki vagy?") == "Igen, Teremtőm."
    assert c.active_backend() is Backend.EDGE
    assert [p.host for p in halo.peldanyok] == [EDGE]


def test_a_felho_HIBAJA_is_edge_re_esik(monkeypatch):
    """Elérhető, de a generálás elhasal (OOM, megszakadt alagút) — nem néma hiba."""
    halo = Halo({CLOUD, EDGE}, **{CLOUD: {"hiba": RuntimeError("boom")},
                                  EDGE: {"valasz": "Az edge felel."}})
    c = kliens(monkeypatch, halo)
    assert c.generate("Ki vagy?") == "Az edge felel."
    assert c.active_backend() is Backend.EDGE


def test_mindket_hatter_halott_LLMUnavailable_az_OKOKKAL(monkeypatch):
    """Ez a safe mode kiváltó jele — és fej nélküli Pi-n az OKOK a diagnózis."""
    halo = Halo(set())
    c = kliens(monkeypatch, halo)
    with pytest.raises(LLMUnavailable, match="cloud.*edge"):
        c.generate("Ki vagy?")
    assert c.active_backend() is None


def test_a_404_megmondja_a_JAVITO_parancsot(monkeypatch):
    """A leggyakoribb üzemi hiba: a modell nincs betöltve azon a gépen."""
    nincs_modell = RuntimeError("model not found")
    nincs_modell.status_code = 404
    halo = Halo({CLOUD}, **{CLOUD: {"hiba": nincs_modell}})
    c = kliens(monkeypatch, halo)
    with pytest.raises(LLMUnavailable, match="ollama pull csaba_ajtony/szabi-8b-v12"):
        c.generate("Ki vagy?")


def test_a_probaja_ROVID_a_generalasa_HOSSZU(monkeypatch):
    """A modul lényege: a rövid korlát a DÖNTÉSÉ, nem a generálásé.

    Közös rövid korláttal a hidegen 21 másodpercig töltő felhő MINDIG kiesne, és a
    robot a demót végig a gyengébb 3B-vel beszélné.
    """
    halo = Halo({CLOUD, EDGE})
    c = kliens(monkeypatch, halo)
    c.generate("Ki vagy?")
    assert halo.peldanyok[0].timeout == 60.0  # generálás: bőven a hidegindítás fölött
    # A VISZONYT kötjük meg, nem a konkrét számot: a próba hangolható (2,0 -> 0,5 a
    # 2026-09-08-i körben), a tétel viszont nem — a döntés próbája nagyságrenddel
    # rövidebb, mint a generálás korlátja. Egy beégetett érték minden hangoláskor
    # elbukna, anélkül hogy bármi valódi elromlott volna.
    assert c._cfg.probe_timeout_s <= c._cfg.cloud_timeout_s / 10


def test_koronkent_ujra_dont_a_hatterrol(monkeypatch):
    """Egy „egyszer edge, mindig edge" kliens a felállt alagutat sosem venné észre.

    A hatókör 2026-09-08 óta a KÖR, nem a kérés: az elérhetetlen host egy körön belül
    megjegyződik (`health/probe.py` — hogy az STT és az LLM ne várja ki KÉTSZER
    ugyanazt az időkorlátot), és a kör elején törlődik. A `uj_kor()` itt tehát nem
    teszt-kozmetika: ez a kör-határ, amit élesben az orchestrator húz meg.
    """
    from freedroid.health.probe import uj_kor

    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    c.generate("első")
    assert c.active_backend() is Backend.EDGE
    halo.elerheto.add(CLOUD)          # az alagút közben felállt
    uj_kor()                          # ÚJ KÖR: a robot újra megkérdezi
    c.generate("második")
    assert c.active_backend() is Backend.CLOUD


def test_egy_KORBEN_csak_egyszer_var_a_halott_felhora(monkeypatch):
    """A Teremtő kérése (2026-09-08): egy körben EGY 0,5 s-os várakozás.

    Az STT (`:8080`) és az LLM (`:11434`) ugyanazt a hostot próbálja. Halott alagútnál
    korábban mindkettő kivárta a saját időkorlátját; most a másodiknak nem kell.
    """
    from freedroid.health.probe import jelold_elerhetetlennek

    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    jelold_elerhetetlennek("http://10.0.0.1:8080")   # az STT már megjárta ezt a hostot
    c.generate("kérdés")

    assert c.active_backend() is Backend.EDGE
    assert CLOUD + "/api/tags" not in halo.probak, \
        "a felhőt MÉGEGYSZER megpróbálta ugyanabban a körben"
    assert "a kör korábbi próbája szerint" in c.decision()


def test_warmup_betolteti_a_modellt_es_bent_tartja(monkeypatch):
    halo = Halo({CLOUD, EDGE})
    c = kliens(monkeypatch, halo)
    assert c.warmup() is Backend.CLOUD
    (hivas,) = halo.peldanyok[0].hivasok
    assert hivas["keep_alive"] == "30m" and hivas["options"]["num_predict"] == 1


def test_warmup_SOSEM_dob(monkeypatch):
    """A bemelegítés kényelem, nem előfeltétel — nem buktathat indulást."""
    halo = Halo({CLOUD}, **{CLOUD: {"hiba": RuntimeError("boom")}})
    c = kliens(monkeypatch, halo)
    assert c.warmup() is None


# --- „melyik modell felelt, és miért?" (a Teremtő kérdése, 2026-08-18) ---

def test_a_dontesi_nyom_megmondja_MELYIK_es_MIERT(monkeypatch):
    """A háttér neve önmagában nem diagnózis: abból nem derül ki, hogy a felhő HALOTT
    volt, vagy csak HIBÁZOTT — a kettő teljesen más javítást kíván."""
    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    c.generate("Ki vagy?")
    indok = c.decision()
    assert "cloud: nem elérhető" in indok and "10.0.0.1" in indok
    assert "edge: felelt (csaba_ajtony/szabi-3b-v12)" in indok
    assert c.active_model() == "csaba_ajtony/szabi-3b-v12"


def test_a_nyom_megkulonbozteti_a_HALOTT_es_a_HIBAZO_felhot(monkeypatch):
    halo = Halo({CLOUD, EDGE}, **{CLOUD: {"hiba": RuntimeError("out of memory")}})
    c = kliens(monkeypatch, halo)
    c.generate("Ki vagy?")
    assert "cloud: RuntimeError: out of memory" in c.decision()


def test_a_kihagyott_hatter_NAPLOZVA_van_de_nem_FIGYELMEZTETESKENT(monkeypatch, caplog):
    """Egy némán edge-re esett kör semmilyen nyomot nem hagyna — pedig pont az érdekes.
    A nyom tehát KÖTELEZŐ; a SZINTJE viszont döntés, és ez a teszt azt rögzíti.

    A kihagyott háttér 2026-08-28-ig WARNING volt, és az első élő menetben KÖRÖNKÉNT
    besárgult egy tökéletesen normális állapotra (nincs felhő). Az ilyen figyelmeztetést
    három perc után senki nem olvassa — vagyis épp a VALÓDIT rejti el. A létra MŰKÖDÉSE
    nem rendellenesség; az összegző sor ugyanazt az indokot INFO-n adja, tehát a
    diagnosztikából semmi nem vész el."""
    import logging
    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    with caplog.at_level(logging.DEBUG, logger="freedroid.llm"):
        c.generate("Ki vagy?")

    szintek = {r.getMessage().split(":")[0]: r.levelno for r in caplog.records}
    assert szintek.get("LLM háttér kihagyva — cloud") == logging.DEBUG, \
        "a kihagyott háttér nyoma kell, de nem figyelmeztetésként"
    assert szintek.get("LLM válasz") == logging.INFO, \
        "az ÖSSZEGZŐ sor viszont alapból is látszódjon — ez hordozza az indokot"
    assert "nem elérhető" in " ".join(r.getMessage() for r in caplog.records), \
        "az INDOK nem veszhet el a szint-váltással"


def test_safe_mode_eseten_is_van_nyom(monkeypatch):
    halo = Halo(set())
    c = kliens(monkeypatch, halo)
    with pytest.raises(LLMUnavailable):
        c.generate("Ki vagy?")
    assert c.decision().endswith("safe mode")


def test_a_host_kinyerese_IPv6_es_sema_nelkul_is_helyes():
    """PR #117 review, mérve. A séma nélküli alak nem elméleti: az URL-ek env-ből
    felülírhatók. Az ÜRES host a legrosszabb eset — két KÜLÖNBÖZŐ gép is ugyanarra a
    kulcsra esne, azaz az egyik bukása a másikat is halottnak jelölné."""
    from freedroid.health.probe import _host

    assert _host("http://10.0.0.1:8080") == "10.0.0.1"
    assert _host("http://[::1]:8080") == "::1"
    assert _host("10.0.0.1:8080") == "10.0.0.1"
    assert _host("http://10.0.0.1:8080") != _host("http://10.0.0.2:11434")


# ── a tartalék SOSEM lehet hideg (mérve 2026-09-08, élő menet) ──────────────────

def test_MINDKET_hattert_bemelegiti_nem_csak_az_elsot(monkeypatch):
    """🔴 A 148 körös menet leggyorsabban demót ölő hibája. A warmup az első sikernél
    visszatért, tehát élő felhő mellett az EDGE modellje soha nem töltődött be. Amikor a
    `terraform destroy` 50 perc után elvitte a felhőt, az első edge-hívás HIDEGEN indult,
    90 s-nál időtúllépéssel elhasalt -> safe mode; 80 másodperccel később ugyanaz az edge
    hibátlanul válaszolt."""
    halo = Halo({CLOUD, EDGE})
    c = kliens(monkeypatch, halo)
    assert c.warmup() is Backend.CLOUD          # a visszatérési érték az ELSŐ
    hostok = [p.host for p in halo.peldanyok]
    assert CLOUD in hostok and EDGE in hostok, hostok


def test_az_EDGE_modell_bent_marad_a_memoriaban(monkeypatch):
    """A tartalék első hívása a leglassabb, és az mindig a legrosszabb pillanatra esik."""
    halo = Halo({CLOUD, EDGE})
    c = kliens(monkeypatch, halo)
    c.warmup()
    keep = {p.host: p.hivasok[0]["keep_alive"] for p in halo.peldanyok if p.hivasok}
    assert keep[EDGE] == "-1", keep
    assert keep[CLOUD] == "30m", keep


def test_a_VALODI_hivas_is_visz_keep_alivet(monkeypatch):
    """Enélkül a bemelegítés egyetlen körig tart: egy `keep_alive` nélküli kérés
    visszaállítja a TTL-t az Ollama 5 perces alapértékére, tehát egy fallback-kör UTÁN
    az edge megint kiürülne, és a következő fallback megint hidegen indulna."""
    halo = Halo({EDGE})
    c = kliens(monkeypatch, halo)
    c.generate("Ki vagy?")
    (hivas,) = halo.peldanyok[0].hivasok
    assert hivas["keep_alive"] == "-1"
