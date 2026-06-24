#!/usr/bin/env python3
"""A/B persona-benchmark futtató a Free-Droid (Szabi) projekthez.

Két, már betöltött Ollama modellnek (pl. `freedroid-qwen` és `freedroid-llama`)
felteszi a `persona_benchmark.json` 25 kérdését azonos, determinisztikus
beállításokkal, méri a generálási sebességet, és az eredményt az értékelő
sablon formátumába (egymás melletti összevetés + kézzel kitölthető pontozó
táblák) önti egy `benchmark_eredmeny.md` fájlba.

Használat (az Ollama-nak futnia kell: `ollama serve`):
    python run_benchmark.py
    python run_benchmark.py --model-a freedroid-qwen --model-b freedroid-llama
    python run_benchmark.py --force --json-out
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCHMARK_FILE = HERE / "persona_benchmark.json"
RESULT_FILE = HERE / "benchmark_eredmeny.md"
RAW_FILE = HERE / "benchmark_raw.json"

OLLAMA_URL = "http://localhost:11434/api/generate"

# Determinisztikus beállítás a fair összevetésért — MINDKÉT modellnél azonos.
TEMPERATURE = 0.7
SEED = 42
REQUEST_TIMEOUT = 180.0  # CPU-n a generálás lassú lehet

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
    """Felhasználónak szóló, értelmes hibaüzenet (nem stacktrace)."""


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
def ollama_generate(model: str, prompt: str) -> tuple[str, float | None]:
    """Egy kérdés feltevése az Ollama /api/generate végponton.

    Visszaad: (válasz_szöveg, tokens_per_sec | None). A modell SYSTEM promptja
    a Modelfile-ban van beégetve, ezért itt csak a kérdést küldjük.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE, "seed": SEED},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
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


def run_model(model: str, label: str, kerdesek: list[dict]) -> dict[str, dict]:
    """Mind a 25 kérdés végigfuttatása egy modellen, haladásjelzéssel."""
    n = len(kerdesek)
    eredmenyek: dict[str, dict] = {}
    for i, q in enumerate(kerdesek, 1):
        print(f"  [{label}] {i}/{n} kérdés — {q['id']} ({q['dimenzio']}) ...", file=sys.stderr)
        valasz, tok_s = ollama_generate(model, q["kerdes"])
        eredmenyek[q["id"]] = {"valasz": valasz, "tok_s": tok_s}
    print(f"  [{label}] kész ({model}).", file=sys.stderr)
    return eredmenyek


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


def ordered_dimensions(kerdesek: list[dict]) -> list[str]:
    """Ismert dimenziók a kívánt sorrendben, majd bármi extra a végén."""
    jelenlevo = [q["dimenzio"] for q in kerdesek]
    rendezett = [d for d in DIMENZIO_SORREND if d in jelenlevo]
    extrak = [d for d in dict.fromkeys(jelenlevo) if d not in DIMENZIO_SORREND]
    return rendezett + extrak


def render_markdown(model_a: str, model_b: str, kerdesek: list[dict],
                    res_a: dict[str, dict], res_b: dict[str, dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out: list[str] = []
    out.append("# 🧪 Free-Droid A/B persona-benchmark — eredmény\n")
    out.append(f"*Futtatva: {now}*  ")
    out.append(f"**Model A:** `{model_a}`  ")
    out.append(f"**Model B:** `{model_b}`  ")
    out.append(f"*Beállítás: temperature={TEMPERATURE}, seed={SEED} (mindkét modellnél azonos)*\n")
    out.append("> A `Pont (1-5)` cellákat és az összesítő táblákat kézzel töltsd ki "
               "az `ertekelo_sablon.md` pontozási skálája szerint.\n")

    # Kérdések dimenziónként csoportosítva, egymás mellett a két modell.
    for dim in ordered_dimensions(kerdesek):
        out.append(f"\n## Dimenzió: {dim}\n")
        for q in [k for k in kerdesek if k["dimenzio"] == dim]:
            qid = q["id"]
            a = res_a.get(qid, {})
            b = res_b.get(qid, {})
            out.append(f"### {qid} — {dim}")
            out.append(f"**Kérdés:** {q['kerdes']}\n")
            out.append(f"| | Model A (`{model_a}`) | Model B (`{model_b}`) |")
            out.append("|---|---|---|")
            out.append(f"| Válasz | {md_cell(a.get('valasz', ''))} | {md_cell(b.get('valasz', ''))} |")
            out.append(f"| tok/s | {fmt_speed(a.get('tok_s'))} | {fmt_speed(b.get('tok_s'))} |")
            out.append("| Pont (1-5) | | |")
            out.append("")

    # Összesítő tábla (kézzel kitöltendő) a 6 dimenzióra.
    out.append("\n## Összesítő — pontozás (kézzel kitöltendő)\n")
    out.append("| Dimenzió | Model A pont | Model B pont | Megjegyzés |")
    out.append("|---|---|---|---|")
    for dim in ordered_dimensions(kerdesek):
        out.append(f"| {dim} | | | |")
    out.append("| **Összesen** | | | |")

    # Sebesség-összesítő: átlagos tok/s modellenként.
    avg_a = _atlag([res_a.get(q["id"], {}).get("tok_s") for q in kerdesek])
    avg_b = _atlag([res_b.get(q["id"], {}).get("tok_s") for q in kerdesek])
    out.append("\n## Sebesség-összesítő\n")
    out.append("| | Model A | Model B |")
    out.append("|---|---|---|")
    out.append(f"| Átlagos tok/s | {fmt_speed(avg_a)} | {fmt_speed(avg_b)} |")
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
    ap.add_argument("--model-a", default="freedroid-qwen", help="Model A Ollama-neve")
    ap.add_argument("--model-b", default="freedroid-llama", help="Model B Ollama-neve")
    ap.add_argument("--force", action="store_true",
                    help="írd felül a meglévő benchmark_eredmeny.md-t (különben hiba)")
    ap.add_argument("--json-out", action="store_true",
                    help="a nyers válaszokat is mentsd benchmark_raw.json-be")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if RESULT_FILE.exists() and not args.force:
        print(f"HIBA: {RESULT_FILE.name} már létezik (kézi pontok elveszhetnek).\n"
              f"  Felülíráshoz add meg a --force flaget.", file=sys.stderr)
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

    print(f"Benchmark: {len(kerdesek)} kérdés × 2 modell "
          f"({args.model_a}, {args.model_b})\n", file=sys.stderr)
    try:
        res_a = run_model(args.model_a, "Model A", kerdesek)
        res_b = run_model(args.model_b, "Model B", kerdesek)
    except BenchmarkError as e:
        print(f"\nHIBA: {e}", file=sys.stderr)
        return 1

    RESULT_FILE.write_text(
        render_markdown(args.model_a, args.model_b, kerdesek, res_a, res_b),
        encoding="utf-8",
    )
    print(f"\nKész → {RESULT_FILE}", file=sys.stderr)

    if args.json_out:
        raw = {
            "meta": {
                "futtatva": datetime.now().isoformat(timespec="seconds"),
                "model_a": args.model_a, "model_b": args.model_b,
                "temperature": TEMPERATURE, "seed": SEED,
            },
            "eredmenyek": [
                {"id": q["id"], "dimenzio": q["dimenzio"], "kerdes": q["kerdes"],
                 "model_a": res_a.get(q["id"]), "model_b": res_b.get(q["id"])}
                for q in kerdesek
            ],
        }
        RAW_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Nyers adat → {RAW_FILE}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
