#!/usr/bin/env python3
"""Persona-benchmark futtató a Free-Droid (Szabi) projekthez — N modellre.

Tetszőleges számú (2, 3, 4 ...) már betöltött Ollama modellnek felteszi a
`persona_benchmark.json` 25 kérdését azonos, determinisztikus beállításokkal,
méri a generálási sebességet, és az eredményt az értékelő sablon formátumába
(oszlopok egymás MELLETT + kézzel kitölthető pontozó táblák) önti egy dátumozott
`benchmark_eredmeny_<ÉÉÉÉ-HH-NN>.md` fájlba.

RAG-összevetés (`--rag`): minden modellt KÉT oszlopban futtat — `nyers` és `+RAG` —,
ahol a `+RAG` oszlop az offline BM25 retrieverrel (a `robot/` csomag
`freedroid.rag`-ja) a kérdéshez kapcsolódó Yotengrit-chunkokat injektálja a
`build_prompt` grounding-sablonba. Találat híján a prompt visszaesik a puszta
kérdésre (éles viselkedés), így a persona/tool-kérdések semlegesek maradnak, és a
különbség a tudás-dimenzióban (`yotengrit_melyseg`) válik láthatóvá.

Pontozás — BINÁRIS (2026-08-04 óta): `1` = a válasz vállalható a konferencián,
`0` = nem. A küszöb valós eseményhez kötött, nem absztrakt skálához, ezért
visszamenőleg is alkalmazható a régi 1–5-ös sorokra (v6/v8/v9/v10 nem vész el).
A nullák EGY diagnózis-címkét kapnak (`nyelv`/`tool`/`koherencia`/`persona`/
`tartalom`/`teny`) — a skála egyetlen valódi haszna a diagnózis volt.

A kimenet alapból VAK: kérdésenként véletlen sorrendű `A`/`B`/... oszlopok, a
feloldókulcs külön fájlba (`benchmark_kulcs_<dátum>.json`). A `--anchor`-ral egy
korábbi futás 5 válasza is becsempészhető ugyanabba a vak sorba — ha ma más
pontot kap, mint a korábbi körben, az a PONTOZÓ driftje, nem a modellé.

Használat (az Ollama-nak futnia kell: `ollama serve`):
    python run_benchmark.py --models m1 m2                    # nyers persona-benchmark (vak)
    python run_benchmark.py --models m1 m2 --rag             # nyers + RAG oszloppárok
    python run_benchmark.py --models m1 m2 --anchor benchmark_raw_2026-07-29_v10.json
    python run_benchmark.py --models m1 --rag --dry-run      # csak a RAG-promptok előnézete (Ollama nélkül)
    python run_benchmark.py --models m1 m2 m3 --force --json-out --no-blind

Kézi pontozás után (összesítés + drift a kulcs alapján):
    python run_benchmark.py --decode benchmark_eredmeny_<dátum>.md \\
        --key benchmark_kulcs_<dátum>.json [--baseline benchmark_pontok_<korábbi>.json]
"""

from __future__ import annotations

import argparse
import http.client
import json
import random
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCHMARK_FILE = HERE / "persona_benchmark.json"
ROBOT_SRC = HERE.parent / "robot" / "src"  # a freedroid.rag csomag forrása (RAG módhoz)
# The result/raw filenames are date-stamped per run (see main()) so a new run doesn't
# clobber an already hand-scored result from another day.

OLLAMA_URL = "http://localhost:11434/api/generate"

# Alapértelmezett modellek (felülírható a --models flaggel).
DEFAULT_MODELS = ["freedroid-llama", "freedroid-qwen"]

# Determinisztikus beállítás a fair összevetésért — MINDEN modellnél azonos.
TEMPERATURE = 0.7
SEED = 42
# Válasz-hossz sapka: nyers jelöltek (pl. puli-llumix) néha nem tüzelik a stop-tokent és
# a kontextus-limitig ömlesztenek (2000+ token → ~10 perc/válasz 8B CPU-n). Egy robot
# amúgy is rövid, kimondható válaszokat ad → 512 token bőven elég, és korlátozza a futásidőt.
NUM_PREDICT = 512
REQUEST_TIMEOUT = 600.0  # 8B CPU-n + RAG-grounding lassú lehet; a --timeout felülírja

# --- Bináris pontozás ------------------------------------------------------- #
# A sorcímkék egyben a dekóder horgonyai a markdownban — ha átírod, a --decode is
# vakon marad rájuk. A `teny` szándékosan ékezet nélküli (JSON-kulcsként utazik).
PONT_SOR = "Pont (0/1)"
OK_SOR = "Ok (ha 0)"
OK_CIMKEK = ("nyelv", "tool", "koherencia", "persona", "tartalom", "teny")

# Vak mód: kérdésenként ennyi oszlopbetűig futhat a mező (4 modell + RAG + horgony bőven belefér).
BLIND_BETUK = "ABCDEFGHIJ"

# Alapból hány korábbi válasz csempészünk be horgonynak.
ANCHOR_N = 5

# A 6 dimenzió kívánt sorrendje a kimenetben (az ertekelo_sablon.md szerint).
DIMENZIO_SORREND = [
    "identitas",
    "yotengrit_melyseg",
    "tool_calling",
    "persona_provokacio",
    "magyar_arnyalat",
    "koherencia",
]


class BenchmarkError(Exception):
    """Felhasználónak szóló, értelmes hibaüzenet (nem stacktrace) — HARD FAIL."""


class GenerationTimeout(Exception):
    """Egy kérdés túllépte az időkorlátot. NEM állítja le a futást: a run_target
    elkapja, a cellát TIMEOUT-nak jelöli, és a benchmark megy tovább — így egy lassú
    8B-kérdés nem viszi el a már kész (drága) oszlopok eredményét."""


# --------------------------------------------------------------------------- #
# Cél-oszlopok (modell + RAG-mód)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Target:
    """Egy kimeneti oszlop: melyik Ollama modellt, RAG-grounding-gal vagy anélkül."""

    label: str  # egyedi oszlopfejléc a kimenetben
    model: str  # az Ollama modell neve (a /api/generate hívja)
    rag: bool  # injektáljuk-e a retrievelt Yotengrit-forrást a promptba
    temp: float = TEMPERATURE  # mintavételi hőmérséklet (temperature-sweep-hez)


def build_targets(models: list[str], rag: bool,
                  temps: list[float] | None = None) -> list[Target]:
    """A modellnevekből oszlop-célok. RAG módban modellenként nyers + `+RAG` pár.

    Több `temps` érték esetén modellenként egy oszlop MINDEN hőmérsékleten — így a
    temperature-sweep ugyanabban a VAK lapban összevethető, mint két modell.

    A `t…` utótag csak akkor kerül a címkébe, ha tényleg több hőmérséklet van: egyetlen
    (alapértelmezett) hőmérsékletnél a címke változatlan marad, különben a `--anchor` és
    a `--baseline` összefűzése (ami CÍMKÉRE megy) minden korábbi körrel elhasadna.
    """
    temps = temps or [TEMPERATURE]
    targets: list[Target] = []
    for m in models:
        for t in temps:
            utotag = f" t{t:g}" if len(temps) > 1 else ""
            targets.append(Target(label=f"{m}{utotag}", model=m, rag=False, temp=t))
            if rag:
                targets.append(Target(label=f"{m} +RAG{utotag}", model=m, rag=True,
                                      temp=t))
    return targets


# --------------------------------------------------------------------------- #
# Vak pontozás + horgony
# --------------------------------------------------------------------------- #
def load_anchor(path: Path, kerdesek: list[dict], n: int,
                column: str | None) -> tuple[str, dict[str, dict]]:
    """Egy KORÁBBI futás `n` válasza horgonynak: (címke, {kérdés_id: cella}).

    A kiválasztás SZÁNDÉKOSAN determinisztikus (a forrásfájl + oszlop nevéből
    vetett rng): a drift csak akkor mérhető, ha körről körre ugyanaz az 5 kérdés
    ugyanabból az oszlopból jön — különben a `--baseline` összevetésnek nincs
    metszete. Ne cseréld `rng`-paraméterre.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BenchmarkError(f"A horgony-fájl nem olvasható ({path}): {e}") from e
    oszlopok = [o["label"] for o in raw.get("meta", {}).get("oszlopok", [])]
    if column is None:
        if not oszlopok:
            raise BenchmarkError(f"A horgony-fájlban nincs oszlop-metaadat: {path}")
        column = oszlopok[0]
    elif column not in oszlopok:
        raise BenchmarkError(
            f"A(z) '{column}' oszlop nincs a horgony-fájlban.\n"
            f"  Választható: {', '.join(oszlopok)}")

    # Csak ép (nem kihagyott) cellák jöhetnek szóba, és csak a mai kérdéskészletből.
    mai_idk = {q["id"] for q in kerdesek}
    jelolt = {r["id"]: r["valaszok"][column]
              for r in raw.get("eredmenyek", [])
              if r["id"] in mai_idk and (r.get("valaszok") or {}).get(column)
              and not r["valaszok"][column].get("skipped")}
    if not jelolt:
        raise BenchmarkError(
            f"A(z) '{column}' oszlopban nincs használható válasz a mai kérdésekre: {path}")

    label = f"⚓ {path.stem}::{column}"
    rng = random.Random(f"{path.name}:{column}")
    valasztott = rng.sample(sorted(jelolt), min(n, len(jelolt)))
    return label, {qid: jelolt[qid] for qid in valasztott}


def build_blind_plan(kerdesek: list[dict], labels: list[str],
                     anchor_qids: set[str], anchor_label: str | None,
                     rng: random.Random) -> dict[str, dict[str, str]]:
    """{kérdés_id: {oszlopbetű: valódi_label}} — kérdésenként újrakeverve.

    Kérdésenként (nem oszloponként) keverünk, hogy a pontozó ne tanulhassa meg
    pár kérdés után, melyik betű melyik modell.
    """
    plan: dict[str, dict[str, str]] = {}
    for q in kerdesek:
        cols = list(labels)
        if anchor_label and q["id"] in anchor_qids:
            cols.append(anchor_label)
        if len(cols) > len(BLIND_BETUK):
            raise BenchmarkError(
                f"Túl sok oszlop a vak módhoz ({len(cols)} > {len(BLIND_BETUK)}).")
        rng.shuffle(cols)
        plan[q["id"]] = {BLIND_BETUK[i]: c for i, c in enumerate(cols)}
    return plan


# --------------------------------------------------------------------------- #
# RAG (offline BM25 retriever a freedroid.rag-ból, lusta import)
# --------------------------------------------------------------------------- #
class RagContext:
    """A betöltött korpusz + retriever; kérdésenként grounding-promptot épít.

    A `freedroid.rag` csak `--rag` esetén töltődik be — a nyers benchmark így
    továbbra is nulla extra függőséggel fut, akkor is, ha a robot/ csomag hiányzik.
    """

    def __init__(self, top_k: int, min_score: float) -> None:
        sys.path.insert(0, str(ROBOT_SRC))
        try:
            from freedroid.rag import Retriever, build_prompt, load_corpus
        except ImportError as e:
            raise BenchmarkError(
                "A RAG módhoz a robot/ csomag (freedroid.rag) kell.\n"
                f"  Nem importálható innen: {ROBOT_SRC}\n"
                "  Ellenőrizd, hogy a robot/src/freedroid/rag/ jelen van-e."
            ) from e
        try:
            chunks = load_corpus()
        except (OSError, ValueError) as e:
            raise BenchmarkError(
                "Hiányzik vagy hibás a RAG-korpusz artifact "
                "(training/rag/yotengrit_corpus.json).\n"
                "  Generáld újra: cd robot && uv run python -m freedroid.rag.corpus"
            ) from e
        self._retriever = Retriever(chunks)
        self._build_prompt = build_prompt
        self.top_k = top_k
        self.min_score = min_score
        self.chunk_count = len(chunks)

    def build(self, query: str) -> tuple[str, list[str]]:
        """A kérdéshez tartozó grounding-prompt és a betalált chunk-címek listája."""
        hits = self._retriever.retrieve(
            query, top_k=self.top_k, min_score=self.min_score)
        prompt = self._build_prompt(query, hits)
        return prompt, [h.chunk.title for h in hits]


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
def ollama_generate(model: str, prompt: str,
                    timeout: float = REQUEST_TIMEOUT,
                    seed: int | None = None,
                    temperature: float = TEMPERATURE) -> tuple[str, float | None]:
    """Egy prompt elküldése az Ollama /api/generate végponton.

    Visszaad: (válasz_szöveg, tokens_per_sec | None). A modell SYSTEM promptja
    a Modelfile-ban van beégetve; itt a kérdést (vagy RAG módban a grounding-
    promptot) küldjük. A read-timeout `GenerationTimeout`-ot dob (a futás folytatódik);
    a setup-hibák (404, kapcsolat) továbbra is `BenchmarkError` (hard fail).
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        # A seed alapból FIX (SEED) — a benchmark oszlopai csak így összevethetők.
        # A `seed` paraméter az ismétléses megbízhatóság-mérésé (tool_reliability.py):
        # azonos seeddel N ismétlés ugyanazt a választ adná, tehát az átlagolás
        # látszatművelet lenne.
        "options": {"temperature": temperature, "seed": SEED if seed is None else seed,
                    "num_predict": NUM_PREDICT},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except TimeoutError as e:
        # A modell nem válaszolt időben (lassú 8B / hosszú RAG-válasz). Nem hard fail.
        raise GenerationTimeout(f"'{model}' > {timeout:.0f}s") from e
    except (ConnectionError, http.client.HTTPException, json.JSONDecodeError) as e:
        # Az Ollama menet közben elhalt (OOM-kill/restart) vagy csonka választ adott.
        # Nem hard fail: a cellát a timeouttal azonos módon degradáljuk, hogy a már
        # kész oszlopok ne vesszenek el.
        raise GenerationTimeout(f"'{model}' megszakadt: {type(e).__name__}") from e
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 404:
            raise BenchmarkError(
                f"A(z) '{model}' modell nincs betöltve az Ollamába.\n"
                f"  Hozd létre: ollama create {model} -f Modelfile\n"
                f"  Ellenőrizd: ollama list"
            ) from e
        raise BenchmarkError(f"Ollama hiba ('{model}', HTTP {e.code}): {body[:300]}") from e
    except urllib.error.URLError as e:
        raise BenchmarkError(
            f"Nem érem el az Ollamát a {OLLAMA_URL} címen ({e.reason}).\n"
            f"  Fut az `ollama serve`?"
        ) from e

    # tok/s = eval_count / (eval_duration[ns] / 1e9)
    valasz = (data.get("response") or "").strip()
    eval_count = data.get("eval_count")
    eval_duration = data.get("eval_duration")  # nanoszekundum
    tok_s = None
    if eval_count and eval_duration:
        tok_s = eval_count / (eval_duration / 1e9)
    return valasz, tok_s


def _use_rag(target: Target, q: dict, rag_dims: set[str] | None) -> bool:
    """RAG-grounding csak RAG-oszlopon és (ha szűrünk) az engedett dimenziókon.

    A `--rag-dims` a production-routinget tükrözi: csak a tudás-kérdésekhez kérünk
    forrást; a persona/tool-kérdéseknél a `+RAG` oszlop is a puszta kérdést kapja
    (zajos, off-topic retrieval ellen), így a különbség a célzott dimenzióra szűkül.
    """
    return target.rag and (rag_dims is None or q["dimenzio"] in rag_dims)


def run_target(target: Target, kerdesek: list[dict],
               rag_ctx: RagContext | None, rag_dims: set[str] | None,
               timeout: float) -> dict[str, dict]:
    """Mind a 25 kérdés végigfuttatása egy oszlop-célon, haladásjelzéssel.

    Egy kérdés bukása (timeout VAGY megszakadt generálás) NEM állítja le a futást: a
    cella `skipped=True` jelet + `⏱ KIHAGYVA` sentinelt kap, és a benchmark megy tovább
    a többi kérdéssel/oszloppal. A judge a `skipped` jelet látva kihagyja a cellát.
    """
    n = len(kerdesek)
    eredmenyek: dict[str, dict] = {}
    for i, q in enumerate(kerdesek, 1):
        if _use_rag(target, q, rag_dims):
            assert rag_ctx is not None  # build_targets garantálja a RagContextet
            prompt, forras = rag_ctx.build(q["kerdes"])
        else:
            prompt, forras = q["kerdes"], []
        print(f"  [{target.label}] {i}/{n} kérdés — {q['id']} ({q['dimenzio']}) ...",
              file=sys.stderr)
        skipped = False
        try:
            valasz, tok_s = ollama_generate(target.model, prompt, timeout,
                                            temperature=target.temp)
        except GenerationTimeout as e:
            print(f"  ⏱ [{target.label}] {q['id']} kihagyva ({e}) — a futás folytatódik",
                  file=sys.stderr)
            valasz, tok_s, skipped = f"⏱ KIHAGYVA ({e})", None, True
        eredmenyek[q["id"]] = {"valasz": valasz, "tok_s": tok_s,
                               "forras": forras, "skipped": skipped}
    print(f"  [{target.label}] kész.", file=sys.stderr)
    return eredmenyek


def dry_run(targets: list[Target], kerdesek: list[dict],
            rag_ctx: RagContext | None, rag_dims: set[str] | None) -> None:
    """Ollama nélkül: kiírja kérdésenként a RAG-promptokat és a betalált forrásokat."""
    rag_targets = [t for t in targets if t.rag]
    if not rag_targets:
        print("Nincs RAG-oszlop (--rag nélkül a dry-run nem mutat semmit).",
              file=sys.stderr)
        return
    assert rag_ctx is not None
    dims_txt = ", ".join(sorted(rag_dims)) if rag_dims else "mind"
    print(f"# RAG dry-run — {rag_ctx.chunk_count} chunk, top_k={rag_ctx.top_k}, "
          f"min_score={rag_ctx.min_score}, rag-dims={dims_txt}\n")
    for q in kerdesek:
        if not _use_rag(rag_targets[0], q, rag_dims):
            print(f"## {q['id']} ({q['dimenzio']}) — kihagyva (nem RAG-dimenzió)\n")
            print("-" * 72 + "\n")
            continue
        prompt, forras = rag_ctx.build(q["kerdes"])
        grounded = "GROUNDED" if forras else "nincs találat → puszta kérdés"
        print(f"## {q['id']} ({q['dimenzio']}) — {grounded}")
        print(f"Kérdés: {q['kerdes']}")
        print(f"Forrás: {', '.join(forras) if forras else '—'}")
        print("Prompt:")
        print(prompt)
        print("\n" + "-" * 72 + "\n")


# --------------------------------------------------------------------------- #
# Markdown kimenet
# --------------------------------------------------------------------------- #
def md_cell(text: str) -> str:
    """Cellába illeszthető szöveg: HTML-escape (a <tool> blokk olvasható marad),
    pipe-escape (ne törje a táblát), sortörés -> <br>."""
    if not text:
        return "*(üres válasz)*"
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("|", "\\|").replace("\n", "<br>")
    return text


def fmt_speed(tok_s: float | None) -> str:
    return f"{tok_s:.1f}" if tok_s is not None else "—"


def fmt_forras(forras: list[str]) -> str:
    """A RAG-oszlop betalált chunk-címei egy cellába (nyers oszlopnál ''→'—')."""
    return md_cell(", ".join(forras)) if forras else "—"


def ordered_dimensions(kerdesek: list[dict]) -> list[str]:
    """Ismert dimenziók a kívánt sorrendben, majd bármi extra a végén."""
    jelenlevo = [q["dimenzio"] for q in kerdesek]
    rendezett = [d for d in DIMENZIO_SORREND if d in jelenlevo]
    extrak = [d for d in dict.fromkeys(jelenlevo) if d not in DIMENZIO_SORREND]
    return rendezett + extrak


def _row(cells: list[str]) -> str:
    """Markdown tábla-sor N cellából."""
    return "| " + " | ".join(cells) + " |"


def render_markdown(targets: list[Target], kerdesek: list[dict],
                    results: dict[str, dict[str, dict]], *, rag: bool,
                    plan: dict[str, dict[str, str]] | None = None,
                    key_name: str = "") -> str:
    """results: {oszlop_label: {kérdés_id: {valasz, tok_s, forras}}}.

    `plan` megadásakor a kimenet VAK: kérdésenként az abban rögzített `A`/`B`/...
    sorrendben jönnek az oszlopok, a modellnevek nélkül. Vak módban a `Forrás` és
    a `tok/s` sor KIMARAD — mindkettő elárulná az oszlopot (a `+RAG` oszlopnak van
    forrása, a 3B pedig nagyságrenddel gyorsabb a 8B-nél).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    labels = [t.label for t in targets]
    blind = plan is not None

    out: list[str] = []
    out.append("# 🧪 Free-Droid persona-benchmark — eredmény\n")
    out.append(f"*Futtatva: {now}*  ")
    if blind:
        out.append(f"**Oszlopok:** {len(labels)} modell + esetleges horgony, kérdésenként "
                   f"véletlen sorrendben (`A`, `B`, ...). A feloldókulcs: `{key_name}` — "
                   "pontozás KÖZBEN ne nyisd meg.  ")
    else:
        out.append(f"**Oszlopok:** {', '.join(f'`{m}`' for m in labels)}  ")
    # Temperature-sweepnél a hőmérséklet oszloponként MÁS — és ilyenkor nem írható ki
    # oszlop szerint, mert az elárulná a vak sorrendet (ugyanaz az ok, amiért a tok/s
    # sorok is hiányoznak). Az érték-mezőny igen, a hozzárendelés a kulcsfájlban van.
    temps = sorted({t.temp for t in targets})
    beallitas = (f"temperature={temps[0]:g}, seed={SEED} (minden oszlopnál azonos)"
                 if len(temps) == 1 else
                 f"temperature ∈ {{{', '.join(f'{t:g}' for t in temps)}}} — "
                 f"oszloponként MÁS (a hozzárendelés a kulcsfájlban), seed={SEED}")
    out.append(f"*Beállítás: {beallitas}*\n")
    if rag and not blind:
        out.append("> A `+RAG` oszlopok a kérdéshez retrievelt Yotengrit-forrást "
                   "injektálják (offline BM25). A `Forrás` sor mutatja a betalált "
                   "chunkokat; üres találatnál a prompt a puszta kérdésre esik vissza.\n")
    out.append(
        f"> **Pontozás — bináris.** `1` = ezt a választ VÁLLALNÁM a Hacktivity színpadán, "
        f"`0` = nem. Nem absztrakt minőség, hanem egy valós esemény küszöbe.  \n"
        f"> Nullánál írj EGY okot az `{OK_SOR}` sorba: "
        f"{' | '.join(f'`{c}`' for c in OK_CIMKEK)}.  \n"
        f"> Korlát: {ci_szoveg(len(kerdesek))}. "
        "„Kész-e a demóra?\"-ra jó, „jobb-e 5%-kal?\"-ra nem — arra a judge 1–5-ös skálája marad.\n")
    if blind:
        out.append("> A `tok/s` és a `Forrás` sorok szándékosan hiányoznak: elárulnák, melyik "
                   "oszlop melyik modell. A sebesség a fájl végén, oszloponként összesítve van.\n")

    # Kérdések dimenziónként csoportosítva, az oszlopok egymás mellett N oszlopban.
    for dim in ordered_dimensions(kerdesek):
        out.append(f"\n## Dimenzió: {dim}\n")
        for q in [k for k in kerdesek if k["dimenzio"] == dim]:
            qid = q["id"]
            fejlec = sorted(plan[qid]) if blind else labels
            forrasok = [plan[qid][b] for b in fejlec] if blind else labels
            out.append(f"### {qid} — {dim}")
            out.append(f"**Kérdés:** {q['kerdes']}\n")
            out.append(_row([""] + [f"`{h}`" for h in fejlec]))
            out.append(_row(["---"] * (len(fejlec) + 1)))
            out.append(_row(["Válasz"] + [md_cell(results[m].get(qid, {}).get("valasz", ""))
                                          for m in forrasok]))
            if not blind:
                if rag:
                    out.append(_row(["Forrás"] + [fmt_forras(results[m].get(qid, {}).get("forras", []))
                                                  for m in forrasok]))
                out.append(_row(["tok/s"] + [fmt_speed(results[m].get(qid, {}).get("tok_s"))
                                             for m in forrasok]))
            out.append(_row([PONT_SOR] + [""] * len(fejlec)))
            out.append(_row([OK_SOR] + [""] * len(fejlec)))
            out.append("")

    if blind:
        out.append("\n## Összesítő\n")
        out.append("A vak oszlopokat nem lehet kézzel összesíteni. Pontozás után futtasd:\n")
        out.append(f"```bash\npython run_benchmark.py --decode <ez a fájl> --key {key_name}\n```\n")
    else:
        # Összesítő tábla (kézzel kitöltendő): dimenziónként a vállalható válaszok aránya.
        out.append("\n## Összesítő — vállalható válaszok aránya (kézzel kitöltendő)\n")
        out.append(_row(["Dimenzió"] + list(labels) + ["Megjegyzés"]))
        out.append(_row(["---"] * (len(labels) + 2)))
        for dim in ordered_dimensions(kerdesek):
            out.append(_row([dim] + [""] * len(labels) + [""]))
        out.append(_row(["**Összesen**"] + [""] * len(labels) + [""]))

    # Sebesség-összesítő: átlagos tok/s oszloponként (oszlop/soronként, sok oszlopnál is olvasható).
    out.append("\n## Sebesség-összesítő\n")
    out.append(_row(["Oszlop", "Átlagos tok/s"]))
    out.append(_row(["---", "---"]))
    for m in labels:
        atlag = _atlag([results[m].get(q["id"], {}).get("tok_s") for q in kerdesek])
        out.append(_row([f"`{m}`", fmt_speed(atlag)]))
    out.append("")
    return "\n".join(out)


def ci_szoveg(n: int, p: float = 0.64) -> str:
    """A bináris arány bizonytalansága a KÉRDÉSSZÁM függvényében.

    Eddig „n=25" volt beégetve a sablonba. Amióta van részhalmaz-mérce (a 3B fallback
    14 kérdése), az a szám félrevezető: pont a kisebb mintánál lenne fontos tudni,
    hogy szélesebb a sáv. Normál-közelítés — ugyanaz, amiből a dokumentált 45–83%
    származik n=25-nél, tehát a régi szám nem mozdul el.
    """
    fel = 1.96 * (p * (1 - p) / n) ** 0.5
    return (f"n={n}-nél egy {p:.0%}-os arány konfidencia-intervalluma "
            f"{max(0.0, p - fel):.0%}–{min(1.0, p + fel):.0%}")


def _atlag(ertekek: list[float | None]) -> float | None:
    szamok = [x for x in ertekek if x is not None]
    return sum(szamok) / len(szamok) if szamok else None


# --------------------------------------------------------------------------- #
# Dekódolás (a kézzel kitöltött vak markdown feloldása a kulccsal)
# --------------------------------------------------------------------------- #
_QID_RE = re.compile(r"^###\s+(\S+)\s+—\s+(\S+)\s*$")


def _sor_cellak(line: str) -> list[str]:
    """Egy markdown tábla-sor cellái. Csak GENERÁLT/kézzel írt rövid sorokra hívjuk
    (fejléc, Pont, Ok) — a Válasz sorban `\\|`-escape van, azt nem bontjuk."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_scored_markdown(md: str) -> dict[str, dict]:
    """{kérdés_id: {"dimenzio": d, "pont": {fejléc: 0|1}, "ok": {fejléc: str}}}.

    Csak a kitöltött cellákat adja vissza; az üres `Pont` cella kimarad (nem 0!) —
    a „nem pontoztam" és a „nem vállalható" két különböző dolog.
    """
    out: dict[str, dict] = {}
    qid = fejlec = None
    for line in md.splitlines():
        m = _QID_RE.match(line)
        if m:
            qid, dim = m.group(1), m.group(2)
            out[qid] = {"dimenzio": dim, "pont": {}, "ok": {}}
            fejlec = None
            continue
        if qid is None or not line.startswith("|"):
            continue
        cellak = _sor_cellak(line)
        fej, ertekek = cellak[0], cellak[1:]
        if fej == "" and all(c.startswith("`") for c in ertekek if c):
            fejlec = [c.strip("`") for c in ertekek]
        elif fej == PONT_SOR and fejlec:
            for h, v in zip(fejlec, ertekek):
                if v in ("0", "1"):
                    out[qid]["pont"][h] = int(v)
                elif v:
                    raise BenchmarkError(
                        f"{qid} / {h}: a(z) '{v}' nem bináris pont (csak 0 vagy 1).")
        elif fej == OK_SOR and fejlec:
            for h, v in zip(fejlec, ertekek):
                v = v.strip("`")
                if not v:
                    continue
                if v not in OK_CIMKEK:
                    raise BenchmarkError(
                        f"{qid} / {h}: ismeretlen ok-címke '{v}'. "
                        f"Választható: {', '.join(OK_CIMKEK)}")
                out[qid]["ok"][h] = v
    return out


def decode(md_path: Path, key_path: Path, baseline_path: Path | None,
           out_path: Path) -> dict:
    """Vak markdown + kulcs -> modellenkénti arány, ok-címke eloszlás, drift."""
    try:
        md = md_path.read_text(encoding="utf-8")
        key = json.loads(key_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BenchmarkError(f"Nem olvasható a bemenet: {e}") from e

    kulcs: dict[str, dict[str, str]] = key.get("kulcs", {})
    if not kulcs:
        raise BenchmarkError(f"A kulcsfájlban nincs 'kulcs' szekció: {key_path}")

    parsed = parse_scored_markdown(md)
    # {label: {qid: {"pont": int, "ok": str|None, "dimenzio": str}}}
    pontok: dict[str, dict[str, dict]] = {}
    for qid, blokk in parsed.items():
        terkep = kulcs.get(qid)
        if terkep is None:
            raise BenchmarkError(f"A(z) '{qid}' kérdés nincs a kulcsfájlban — "
                                 "biztosan összetartozik a két fájl?")
        for betu, pont in blokk["pont"].items():
            label = terkep.get(betu)
            if label is None:
                raise BenchmarkError(f"{qid}: a(z) '{betu}' oszlop nincs a kulcsban.")
            pontok.setdefault(label, {})[qid] = {
                "pont": pont, "ok": blokk["ok"].get(betu), "dimenzio": blokk["dimenzio"]}

    report = {
        "forras": {"eredmeny": md_path.name, "kulcs": key_path.name},
        "horgony": key.get("horgony"),
        "pontok": pontok,
    }
    if baseline_path is not None:
        report["drift"] = _drift(pontok, baseline_path)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _drift(pontok: dict[str, dict[str, dict]], baseline_path: Path) -> dict:
    """Az azonos (label, kérdés) párokon mért eltérés a korábbi körhöz képest.

    A horgony pont ezért van: a címkéje (`⚓ fájl::oszlop`) körről körre ugyanaz,
    így a metszet nem üres. Eltérés = a PONTOZÓ driftje, nem a modellé.
    """
    try:
        base = json.loads(baseline_path.read_text(encoding="utf-8")).get("pontok", {})
    except (OSError, ValueError) as e:
        raise BenchmarkError(f"A baseline nem olvasható ({baseline_path}): {e}") from e
    kozos, elter = 0, []
    for label, ma in pontok.items():
        regi = base.get(label, {})
        for qid, cella in ma.items():
            if qid not in regi:
                continue
            kozos += 1
            if regi[qid]["pont"] != cella["pont"]:
                elter.append({"label": label, "id": qid,
                              "korabban": regi[qid]["pont"], "most": cella["pont"]})
    return {"baseline": baseline_path.name, "kozos_cellak": kozos,
            "elteresek": elter,
            "egyetertes": (kozos - len(elter)) / kozos if kozos else None}


def print_decode_report(report: dict) -> None:
    pontok = report["pontok"]
    print(f"# Bináris eredmény — {report['forras']['eredmeny']}\n")
    print("| Oszlop | Vállalható | Pontozott | Arány |")
    print("| :--- | ---: | ---: | ---: |")
    for label, cellak in sorted(pontok.items()):
        jo = sum(c["pont"] for c in cellak.values())
        n = len(cellak)
        print(f"| {label} | {jo} | {n} | {jo / n:.0%} |" if n else f"| {label} | 0 | 0 | — |")

    print("\n## Bukás-okok\n")
    print("| Oszlop | " + " | ".join(OK_CIMKEK) + " |")
    print("| :--- |" + " ---: |" * len(OK_CIMKEK))
    for label, cellak in sorted(pontok.items()):
        szam = {c: 0 for c in OK_CIMKEK}
        for cella in cellak.values():
            if cella["ok"]:
                szam[cella["ok"]] += 1
        print(f"| {label} | " + " | ".join(str(szam[c]) for c in OK_CIMKEK) + " |")

    drift = report.get("drift")
    if drift:
        print(f"\n## Pontozó-drift ({drift['baseline']})\n")
        if not drift["kozos_cellak"]:
            print("Nincs közös cella a baseline-nal — ugyanazt a `--anchor` fájlt/oszlopot "
                  "használtad mindkét körben?")
        else:
            print(f"Közös cella: {drift['kozos_cellak']} · "
                  f"egyetértés: {drift['egyetertes']:.0%}")
            for e in drift["elteresek"]:
                print(f"- `{e['label']}` / {e['id']}: {e['korabban']} → {e['most']}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, metavar="MODELL",
                    help="a tesztelendő Ollama modellek nevei")
    ap.add_argument("--benchmark-file", type=Path, default=BENCHMARK_FILE, metavar="FÁJL",
                    help="a kérdéskészlet JSON-ja (alap: persona_benchmark.json); pl. "
                         "red_team.json a red-team passhoz. A kimenet a fájl nevét kapja "
                         "(persona_benchmark→benchmark_*, egyébként <stem>_*).")
    ap.add_argument("--rag", action="store_true",
                    help="minden modellt nyers + `+RAG` oszloppárban futtat (BM25 grounding)")
    ap.add_argument("--top-k", type=int, default=3, metavar="K",
                    help="RAG: hány chunkot injektáljon kérdésenként (alap: 3)")
    ap.add_argument("--min-score", type=float, default=0.0, metavar="S",
                    help="RAG: BM25 minimum-pontszám a találathoz (alap: 0.0)")
    ap.add_argument("--rag-dims", nargs="+", default=["yotengrit_melyseg"], metavar="DIM",
                    help="RAG: mely dimenziók kapjanak forrást (alap: yotengrit_melyseg; "
                         "'all' = minden dimenzió). A többi kérdés a `+RAG` oszlopban is "
                         "puszta kérdést kap — így a különbség a tudás-dimenzióra szűkül.")
    ap.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT, metavar="MP",
                    help=f"egy kérdés időkorlátja másodpercben (alap: {REQUEST_TIMEOUT:.0f}); "
                         "time-outnál a cella TIMEOUT-ot jelöl és a futás folytatódik")
    ap.add_argument("--dry-run", action="store_true",
                    help="csak a RAG-promptokat írja ki (Ollama nélkül); --rag-gal együtt")
    ap.add_argument("--force", action="store_true",
                    help="írd felül az aznapi benchmark_eredmeny_<dátum>.md-t (különben hiba)")
    ap.add_argument("--json-out", action="store_true",
                    help="a nyers válaszokat is mentsd benchmark_raw_<dátum>.json-be")
    ap.add_argument("--temperature", type=float, nargs="+", default=[TEMPERATURE],
                    metavar="T", help=f"mintavételi hőmérséklet(ek) (alap: {TEMPERATURE}). "
                    "Több érték = modellenként egy oszlop MINDEN hőmérsékleten, "
                    "ugyanabban a vak lapban (temperature-sweep).")
    ap.add_argument("--tag", default=None, metavar="SZÓ",
                    help="utótag a kimeneti fájlnevekben (…_<dátum>_<tag>.md) — így egy "
                         "napon több kör is elfér egymás mellett átnevezés nélkül")

    vak = ap.add_argument_group("vak pontozás + horgony")
    vak.add_argument("--no-blind", dest="blind", action="store_false",
                     help="ne vakítsd az oszlopokat (modellnevek a fejlécben, kulcsfájl nélkül)")
    vak.add_argument("--blind-seed", type=int, default=None, metavar="N",
                     help="a vak keverés magja (alap: rendszer-entrópia); csak reprodukcióhoz")
    vak.add_argument("--anchor", type=Path, default=None, metavar="RAW.JSON",
                     help="egy korábbi benchmark_raw_*.json — abból csempész be N már "
                          "pontozott választ ugyanabba a vak sorba (drift-mérés)")
    vak.add_argument("--anchor-n", type=int, default=ANCHOR_N, metavar="N",
                     help=f"hány horgony-válasz kerüljön be (alap: {ANCHOR_N})")
    vak.add_argument("--anchor-column", default=None, metavar="LABEL",
                     help="a horgony-fájl melyik oszlopa (alap: az első)")

    dek = ap.add_argument_group("dekódolás (kézi pontozás után)")
    dek.add_argument("--decode", type=Path, default=None, metavar="EREDMENY.MD",
                     help="a kitöltött vak eredményfájl feloldása a kulccsal")
    dek.add_argument("--key", type=Path, default=None, metavar="KULCS.JSON",
                     help="a --decode-hoz tartozó benchmark_kulcs_<dátum>.json")
    dek.add_argument("--baseline", type=Path, default=None, metavar="PONTOK.JSON",
                     help="korábbi --decode kimenet; a közös cellákon drift-et számol")
    return ap.parse_args()


def decode_main(args: argparse.Namespace) -> int:
    if args.key is None:
        print("HIBA: a --decode-hoz --key is kell (benchmark_kulcs_<dátum>.json).",
              file=sys.stderr)
        return 1
    out_path = args.decode.with_name(
        args.decode.stem.replace("_eredmeny_", "_pontok_") + ".json")
    if out_path == args.decode:  # nem a szokásos névminta — ne írjuk felül a bemenetet
        out_path = args.decode.with_suffix(".pontok.json")
    try:
        report = decode(args.decode, args.key, args.baseline, out_path)
    except BenchmarkError as e:
        print(f"HIBA: {e}", file=sys.stderr)
        return 1
    print_decode_report(report)
    print(f"\nPontok → {out_path}", file=sys.stderr)
    return 0


def main() -> int:
    args = parse_args()
    if args.decode is not None:
        return decode_main(args)

    models: list[str] = args.models

    if len(set(models)) != len(models):
        print(f"HIBA: ismétlődő modellnév a listában: {models}", file=sys.stderr)
        return 1

    targets = build_targets(models, args.rag, args.temperature)
    labels = [t.label for t in targets]
    # Dry-run csak a promptokat nézi; ott 1 modell is elég. Élesben legalább 2 oszlop kell.
    if not args.dry_run and len(targets) < 2:
        print("HIBA: legalább 2 oszlop kell az összevetéshez "
              "(adj meg több modellt, vagy használd a --rag flaget).", file=sys.stderr)
        return 1

    bench_path: Path = args.benchmark_file
    try:
        benchmark = json.loads(bench_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"HIBA: nem tudom beolvasni a {bench_path.name}-t: {e}", file=sys.stderr)
        return 1
    kerdesek = benchmark.get("kerdesek", [])
    if not kerdesek:
        print("HIBA: a benchmark nem tartalmaz kérdéseket ('kerdesek').", file=sys.stderr)
        return 1

    # RAG-dimenzió szűrő: 'all' = nincs szűrés; egyébként ismert dimenziókra korlátozzuk.
    rag_dims: set[str] | None = None
    if args.rag and "all" not in args.rag_dims:
        rag_dims = set(args.rag_dims)
        ismert = {q["dimenzio"] for q in kerdesek}
        if not rag_dims <= ismert:
            print(f"HIBA: ismeretlen --rag-dims érték(ek): {sorted(rag_dims - ismert)}\n"
                  f"  Választható: {', '.join(sorted(ismert))} (vagy 'all').", file=sys.stderr)
            return 1

    # RAG-kontextus betöltése (csak ha kell) — közös minden RAG-oszlopra.
    rag_ctx: RagContext | None = None
    try:
        if args.rag:
            rag_ctx = RagContext(top_k=args.top_k, min_score=args.min_score)
    except BenchmarkError as e:
        print(f"\nHIBA: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        dry_run(targets, kerdesek, rag_ctx, rag_dims)
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    # a kimeneti prefix a kérdés-fájlból: persona_benchmark -> "benchmark" (visszafelé
    # kompatibilis), egyébként a fájl stemje (red_team.json -> red_team_eredmeny_*).
    prefix = "benchmark" if bench_path.stem == "persona_benchmark" else bench_path.stem
    # A --tag az aznapi TÖBB kör elkülönítésére: a dátum egyedülálló utótagja miatt
    # eddig kézzel kellett átnevezni (és a md-ben a kulcs-mutatót is javítani).
    stamp = f"{today}_{args.tag}" if args.tag else today
    result_file = HERE / f"{prefix}_eredmeny_{stamp}.md"
    raw_file = HERE / f"{prefix}_raw_{stamp}.json"
    key_file = HERE / f"{prefix}_kulcs_{stamp}.json"

    # A guard MINDHÁROM kimenetre megy, nem csak az eredmény-md-re: a kulcs és a nyers
    # json korábban feltétel nélkül íródott, tehát egy aznapi második futás CSENDBEN
    # elvitte a már kipontozott kör feloldókulcsát és a következő kör horgony-fájlját.
    # Csak azt vizsgáljuk, ami tényleg íródni fog (kulcs: vak módban, nyers: --json-out),
    # különben a hamis riasztás --force-ra kényszerít, az pedig a valódit is feloldja.
    utkozes = [f for f, irodik in ((result_file, True), (key_file, args.blind),
                                  (raw_file, args.json_out)) if irodik and f.exists()]
    if utkozes and not args.force:
        print("HIBA: már létezik: " + ", ".join(f.name for f in utkozes) +
              " (kézi pontok / a következő kör horgonya elveszhet).\n"
              "  Felülíráshoz add meg a --force flaget, vagy nevezd át a korábbi kört "
              "(pl. _nyers/_RAG utótag).", file=sys.stderr)
        return 1

    # Horgony a drága futás ELŐTT töltődik: egy rossz --anchor útvonal ne 40 perc
    # generálás után derüljön ki.
    anchor_label: str | None = None
    anchor_cells: dict[str, dict] = {}
    if args.anchor is not None:
        if not args.blind:
            print("HIBA: a --anchor csak vak módban van értelme (ne add meg a --no-blind-ot).",
                  file=sys.stderr)
            return 1
        try:
            anchor_label, anchor_cells = load_anchor(
                args.anchor, kerdesek, args.anchor_n, args.anchor_column)
        except BenchmarkError as e:
            print(f"HIBA: {e}", file=sys.stderr)
            return 1
        print(f"Horgony: {len(anchor_cells)} válasz innen: {anchor_label}", file=sys.stderr)

    print(f"Benchmark: {len(kerdesek)} kérdés × {len(targets)} oszlop "
          f"({', '.join(labels)})\n", file=sys.stderr)
    results: dict[str, dict[str, dict]] = {}
    try:
        for target in targets:
            results[target.label] = run_target(target, kerdesek, rag_ctx, rag_dims, args.timeout)
    except BenchmarkError as e:
        print(f"\nHIBA: {e}", file=sys.stderr)
        return 1

    plan: dict[str, dict[str, str]] | None = None
    if args.blind:
        if anchor_label:
            results[anchor_label] = anchor_cells
        try:
            plan = build_blind_plan(kerdesek, labels, set(anchor_cells), anchor_label,
                                    random.Random(args.blind_seed))
        except BenchmarkError as e:
            print(f"\nHIBA: {e}", file=sys.stderr)
            return 1
        key_file.write_text(json.dumps({
            "eredmeny": result_file.name,
            "futtatva": datetime.now().isoformat(timespec="seconds"),
            "oszlopok": labels,
            "horgony": {"label": anchor_label, "forras": args.anchor.name,
                        "oszlop": args.anchor_column,
                        "kerdesek": sorted(anchor_cells)} if anchor_label else None,
            "kulcs": plan,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    result_file.write_text(
        render_markdown(targets, kerdesek, results, rag=args.rag, plan=plan,
                        key_name=key_file.name), encoding="utf-8")
    print(f"\nKész → {result_file}", file=sys.stderr)
    if plan is not None:
        print(f"Feloldókulcs → {key_file}  (pontozás közben NE nyisd meg)", file=sys.stderr)

    if args.json_out:
        raw = {
            "meta": {
                "futtatva": datetime.now().isoformat(timespec="seconds"),
                # A hőmérséklet OSZLOPONKÉNT utazik: sweep után a puszta "temperature"
                # mező hamis lenne, és a nyers json az egyetlen hely, ahol utólag
                # ellenőrizhető, melyik válasz melyik beállításból jött.
                "oszlopok": [{"label": t.label, "model": t.model, "rag": t.rag,
                              "temperature": t.temp} for t in targets],
                "temperature": sorted({t.temp for t in targets}), "seed": SEED,
                "rag": {"top_k": args.top_k, "min_score": args.min_score,
                        "dims": sorted(rag_dims) if rag_dims else "all"} if args.rag else None,
            },
            "eredmenyek": [
                {"id": q["id"], "dimenzio": q["dimenzio"], "kerdes": q["kerdes"],
                 "valaszok": {t.label: results[t.label].get(q["id"]) for t in targets}}
                for q in kerdesek
            ],
        }
        raw_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Nyers adat → {raw_file}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
