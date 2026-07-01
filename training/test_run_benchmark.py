#!/usr/bin/env python3
"""A run_benchmark.py timeout-rezilienciájának ellenőrzése (hálózat nélkül).

Futtatás: `python test_run_benchmark.py` vagy `pytest test_run_benchmark.py`.
Csak a hozzáadott elágazást fedi: egy kérdés time-outja NEM állíthatja le a futást
(különben a már kész, drága oszlopok eredménye elveszne), a setup-hiba viszont igen.
"""

import run_benchmark as rb

_KERDESEK = [{"id": f"q{i}", "dimenzio": "koherencia", "kerdes": "?"} for i in range(3)]
_TARGET = rb.Target(label="teszt", model="m", rag=False)


def _raise(exc):
    def _f(model, prompt, timeout):
        raise exc
    return _f


def test_timeout_degrades_and_run_continues() -> None:
    orig = rb.ollama_generate
    rb.ollama_generate = _raise(rb.GenerationTimeout("'m' > 600s"))
    try:
        res = rb.run_target(_TARGET, _KERDESEK, rag_ctx=None, rag_dims=None, timeout=600.0)
    finally:
        rb.ollama_generate = orig
    assert len(res) == 3, "mind a 3 kérdés meglegyen — a futás nem állhatott le"
    assert all(v["valasz"].startswith("⏱ TIMEOUT") for v in res.values())
    assert all(v["tok_s"] is None for v in res.values())


def test_setup_error_still_hard_fails() -> None:
    orig = rb.ollama_generate
    rb.ollama_generate = _raise(rb.BenchmarkError("404 nincs modell"))
    try:
        rb.run_target(_TARGET, _KERDESEK, None, None, 600.0)
    except rb.BenchmarkError:
        return  # elvárt: a setup-hiba felszáll (hard fail)
    finally:
        rb.ollama_generate = orig
    raise AssertionError("a BenchmarkError-nak hard fail-nek kell maradnia")


if __name__ == "__main__":
    test_timeout_degrades_and_run_continues()
    test_setup_error_still_hard_fails()
    print("MIND ZÖLD")
