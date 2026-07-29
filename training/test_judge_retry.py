"""A judge rate-limit retry-logikájának önálló próbája.

Futtatás:  python3 training/test_judge_retry.py

Miért van erre teszt: a `--judge-model` Opusra állítása óta a rate limit VALÓS
kockázat (szűkebb limitek, lassabb válasz, `--max-workers 4`). A hiba némán drága:
korábban egyetlen 429 `JudgeError`-t adott, ami MEGÖLTE a teljes futást, és elvitte
az összes addig elkészült pontozást.

A megőrzendő megkülönböztetés, amit ez a próba őriz:
  * ÁTMENETI (429/529/overload) -> backoff, majd JudgeTimeout = per-kérdés degradáció
  * SZISZTÉMÁS (auth, nincs CLI) -> JudgeError AZONNAL, újrapróbálás nélkül
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("jb", Path(__file__).with_name("judge_benchmark.py"))
jb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jb)


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


ATMENETI = [
    "API Error: 429 rate_limit_error",
    "Error: Rate limit exceeded, please try again later",
    "overloaded_error: 529",
    "Too Many Requests",
]
SZISZTEMAS = [
    "Invalid API key · Please run /login",
    "authentication_error: invalid x-api-key",
    "Error: unknown model 'claude-opus-9'",
    "",
]


def main():
    for s in ATMENETI:
        assert jb._atmeneti_hiba(s), f"nem ismerte fel átmenetinek: {s!r}"
    for s in SZISZTEMAS:
        assert not jb._atmeneti_hiba(s), f"tévesen átmenetinek vette: {s!r}"
    print(f"  OK  minta-felismerés ({len(ATMENETI)} átmeneti + {len(SZISZTEMAS)} szisztémás)")

    jb.time.sleep = lambda _n: None          # a backoff ne várjon a tesztben
    hivas = {"n": 0}

    # 1) átmeneti hiba végig -> retry -> JudgeTimeout (degradál, nem run-killer)
    jb.subprocess.run = lambda *a, **k: (
        hivas.__setitem__("n", hivas["n"] + 1), _Proc(1, err="API Error: 429 rate_limit_error"))[1]
    try:
        jb.call_claude("x", "claude-opus-5", 10, retries=2)
        raise AssertionError("nem dobott kivételt")
    except jb.JudgeTimeout:
        assert hivas["n"] == 3, f"1+2 hívás kellett volna, lett {hivas['n']}"
    print("  OK  rate limit -> 3 próbálkozás -> JudgeTimeout")

    # 2) szisztémás hiba -> AZONNAL JudgeError, retry NÉLKÜL
    hivas["n"] = 0
    jb.subprocess.run = lambda *a, **k: (
        hivas.__setitem__("n", hivas["n"] + 1), _Proc(1, err="Invalid API key · Please run /login"))[1]
    try:
        jb.call_claude("x", "claude-opus-5", 10, retries=2)
        raise AssertionError("nem dobott kivételt")
    except jb.JudgeError:
        assert hivas["n"] == 1, f"auth-hibán NEM szabad újrapróbálni, {hivas['n']} hívás történt"
    print("  OK  auth-hiba -> 1 hívás -> JudgeError")

    # 3) átmeneti, majd siker
    hivas["n"] = 0

    def flaky(*_a, **_k):
        hivas["n"] += 1
        return _Proc(1, err="overloaded_error: 529") if hivas["n"] == 1 \
            else _Proc(0, out='{"result":"5"}')

    jb.subprocess.run = flaky
    assert jb.call_claude("x", "claude-opus-5", 10, retries=2) == "5"
    assert hivas["n"] == 2
    print("  OK  átmeneti majd siker -> 2 hívás, eredmény visszaadva")
    print("\nMind a 3 ág helyes.")


if __name__ == "__main__":
    main()
