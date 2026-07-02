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

Használat (az Ollama-nak futnia kell: `ollama serve`):
    python run_benchmark.py --models m1 m2                    # nyers persona-benchmark
    python run_benchmark.py --models m1 m2 --rag             # nyers + RAG oszloppárok
    python run_benchmark.py --models m1 --rag --dry-run      # csak a RAG-promptok előnézete (Ollama nélkül)
    python run_benchmark.py --models m1 m2 m3 --force --json-out
"""

from __future__ import annotations

import argparse
import json
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


def build_targets(models: list[str], rag: bool) -> list[Target]:
    """A modellnevekből oszlop-célok. RAG módban modellenként nyers + `+RAG` pár."""
    targets: list[Target] = []
    for m in models:
        targets.append(Target(label=m, model=m, rag=False))
        if rag:
            targets.append(Target(label=f"{m} +RAG", model=m, rag=True))
    return targets


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
                    timeout: float = REQUEST_TIMEOUT) -> tuple[str, float | None]:
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
        "options": {"temperature": TEMPERATURE, "seed": SEED,
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

    Egy kérdés time-outja NEM állítja le a futást: a cella `⏱ TIMEOUT` jelölést kap
    (látható a kimenetben) és a benchmark megy tovább a többi kérdéssel/oszloppal.
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
        try:
            valasz, tok_s = ollama_generate(target.model, prompt, timeout)
        except GenerationTimeout as e:
            print(f"  ⏱ [{target.label}] {q['id']} TIMEOUT ({e}) — cella kihagyva, "
                  f"a futás folytatódik", file=sys.stderr)
            valasz, tok_s = f"⏱ TIMEOUT (>{timeout:.0f}s)", None
        eredmenyek[q["id"]] = {"valasz": valasz, "tok_s": tok_s, "forras": forras}
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
                    results: dict[str, dict[str, dict]], *, rag: bool) -> str:
    """results: {oszlop_label: {kérdés_id: {valasz, tok_s, forras}}}."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    labels = [t.label for t in targets]
    sep = _row(["---"] * (len(labels) + 1))  # bal oszlop ("") + N oszlop

    out: list[str] = []
    out.append("# 🧪 Free-Droid persona-benchmark — eredmény\n")
    out.append(f"*Futtatva: {now}*  ")
    out.append(f"**Oszlopok:** {', '.join(f'`{m}`' for m in labels)}  ")
    out.append(f"*Beállítás: temperature={TEMPERATURE}, seed={SEED} (minden oszlopnál azonos)*\n")
    if rag:
        out.append("> A `+RAG` oszlopok a kérdéshez retrievelt Yotengrit-forrást "
                   "injektálják (offline BM25). A `Forrás` sor mutatja a betalált "
                   "chunkokat; üres találatnál a prompt a puszta kérdésre esik vissza.\n")
    out.append("> A `Pont (1-5)` cellákat és az összesítő táblákat kézzel töltsd ki "
               "az `ertekelo_sablon.md` pontozási skálája szerint.\n")

    # Kérdések dimenziónként csoportosítva, az oszlopok egymás mellett N oszlopban.
    for dim in ordered_dimensions(kerdesek):
        out.append(f"\n## Dimenzió: {dim}\n")
        for q in [k for k in kerdesek if k["dimenzio"] == dim]:
            qid = q["id"]
            out.append(f"### {qid} — {dim}")
            out.append(f"**Kérdés:** {q['kerdes']}\n")
            out.append(_row([""] + [f"`{m}`" for m in labels]))
            out.append(sep)
            out.append(_row(["Válasz"] + [md_cell(results[m].get(qid, {}).get("valasz", ""))
                                          for m in labels]))
            if rag:
                out.append(_row(["Forrás"] + [fmt_forras(results[m].get(qid, {}).get("forras", []))
                                              for m in labels]))
            out.append(_row(["tok/s"] + [fmt_speed(results[m].get(qid, {}).get("tok_s"))
                                         for m in labels]))
            out.append(_row(["Pont (1-5)"] + [""] * len(labels)))
            out.append("")

    # Összesítő tábla (kézzel kitöltendő): dimenzió-soronként, oszloponként egy pont-oszlop.
    out.append("\n## Összesítő — pontozás (kézzel kitöltendő)\n")
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


def _atlag(ertekek: list[float | None]) -> float | None:
    szamok = [x for x in ertekek if x is not None]
    return sum(szamok) / len(szamok) if szamok else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, metavar="MODELL",
                    help="a tesztelendő Ollama modellek nevei")
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
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    models: list[str] = args.models

    if len(set(models)) != len(models):
        print(f"HIBA: ismétlődő modellnév a listában: {models}", file=sys.stderr)
        return 1

    targets = build_targets(models, args.rag)
    labels = [t.label for t in targets]
    # Dry-run csak a promptokat nézi; ott 1 modell is elég. Élesben legalább 2 oszlop kell.
    if not args.dry_run and len(targets) < 2:
        print("HIBA: legalább 2 oszlop kell az összevetéshez "
              "(adj meg több modellt, vagy használd a --rag flaget).", file=sys.stderr)
        return 1

    try:
        benchmark = json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"HIBA: nem tudom beolvasni a {BENCHMARK_FILE.name}-t: {e}", file=sys.stderr)
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
    result_file = HERE / f"benchmark_eredmeny_{today}.md"
    raw_file = HERE / f"benchmark_raw_{today}.json"

    if result_file.exists() and not args.force:
        print(f"HIBA: {result_file.name} már létezik (kézi pontok elveszhetnek).\n"
              f"  Felülíráshoz add meg a --force flaget.", file=sys.stderr)
        return 1

    print(f"Benchmark: {len(kerdesek)} kérdés × {len(targets)} oszlop "
          f"({', '.join(labels)})\n", file=sys.stderr)
    results: dict[str, dict[str, dict]] = {}
    try:
        for target in targets:
            results[target.label] = run_target(target, kerdesek, rag_ctx, rag_dims, args.timeout)
    except BenchmarkError as e:
        print(f"\nHIBA: {e}", file=sys.stderr)
        return 1

    result_file.write_text(
        render_markdown(targets, kerdesek, results, rag=args.rag), encoding="utf-8")
    print(f"\nKész → {result_file}", file=sys.stderr)

    if args.json_out:
        raw = {
            "meta": {
                "futtatva": datetime.now().isoformat(timespec="seconds"),
                "oszlopok": [{"label": t.label, "model": t.model, "rag": t.rag}
                             for t in targets],
                "temperature": TEMPERATURE, "seed": SEED,
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
