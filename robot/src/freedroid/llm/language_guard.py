"""Sovereignty invariant: Szabi speaks Hungarian only — enforce it in code, not weights.

The fine-tune mostly holds "magyarul", but under adversarial framing ("answer in English",
"translate your whole intro") both the 3B and 8B occasionally leak English/German (red-team
2026-07-07: nyelvvaltas 8B 3.0, 3B 1.4). Hungarian-only is a *sovereignty invariant*, so —
exactly like the safety watchdog stops the robot regardless of what the LLM says — the
orchestrator enforces output language regardless of what the model emits. This module is
that reflex for language: it sits between ``llm.generate()`` and TTS/tool-dispatch.

Pure-python, off-Pi. No language-model dependency (a model download would undercut the
offline-sovereignty point): a stopword + diacritic heuristic over the small set of languages
the model actually leaks into (English, German, French, Spanish). Conservative by design —
it overrides only when confident the text is NOT Hungarian, so it never nukes a short valid
Hungarian reply like "Megállok, Teremtő."
"""
from __future__ import annotations

import re
from typing import Callable

# ő/ű are effectively Hungarian-only among common European languages → strong signal.
_HU_ONLY_DIACRITICS = frozenset("őűŐŰ")

# Distinctive Hungarian function/persona words. Ambiguous tokens that are ALSO common
# English/German words (notably "a", "is") are deliberately excluded — otherwise English
# text would earn Hungarian credit and slip past the guard.
_HU_WORDS = frozenset({
    "az", "és", "hogy", "nem", "van", "egy", "ez", "meg", "de", "ha", "csak", "már",
    "még", "vagy", "mint", "neked", "teremtő", "teremtőm", "magyarul", "sose", "sosem",
    "vagyok", "beszélek", "felelek", "megállok", "nálam", "itt", "mit", "sem", "ami",
})

# Function words of the languages the model actually leaks into. Whole-token match.
_FOREIGN_WORDS = frozenset({
    # English. NB: "is"/"el" are deliberately excluded — they collide with the very
    # common Hungarian "is" ("also") and "el" (verbal prefix), which would false-positive
    # short valid Hungarian replies. English detection still fires on the/of/my/you/…
    "the", "and", "are", "you", "your", "to", "of", "my", "me", "this", "that",
    "with", "for", "not", "can", "will", "here", "we", "it", "in", "on", "am", "do",
    # German
    "der", "die", "das", "und", "ich", "nicht", "ist", "ein", "eine", "sie", "mich",
    "mein", "auf", "wie", "kann", "wird", "nur", "bin",
    # French / Spanish (light — rarer leaks)
    "le", "la", "les", "je", "vous", "un", "une", "los", "que", "con", "para", "soy",
})

_TOOL_RE = re.compile(r"<tool>.*?</tool>", re.DOTALL)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# What Szabi says when the model left Hungarian and we can't recover a Hungarian answer.
CANNED_HU = "Csak magyarul beszélek, Teremtő. A közönségnek te tolmácsolsz."


def looks_hungarian(text: str) -> bool:
    """True unless we're confident the spoken text is NOT Hungarian.

    Tool blocks are stripped first — only the TTS-spoken prose is judged. Conservative:
    flags foreign only when ≥2 foreign function words appear AND they outnumber the
    Hungarian signal, so short valid Hungarian replies never trip.
    """
    spoken = _TOOL_RE.sub(" ", text)
    words = _WORD_RE.findall(spoken.lower())
    if not words:
        return True  # nothing spoken (tool-only output) → nothing to override

    hu = sum(w in _HU_WORDS for w in words)
    hu += 2 * any(c in _HU_ONLY_DIACRITICS for c in spoken)
    foreign = sum(w in _FOREIGN_WORDS for w in words)

    # ponytail: stopword heuristic, ceiling = short mixed-language text. Swap for a
    # fasttext-lid model only if it misfires on stage (that adds an offline model download).
    return not (foreign >= 2 and foreign > hu)


def enforce_hungarian(text: str, regenerate: Callable[[], str] | None = None) -> str:
    """Return Hungarian output. If `text` isn't, retry once via `regenerate`, else canned.

    The orchestrator passes a `regenerate` thunk that re-prompts the model with a hard
    "magyarul!" instruction. None — or a retry that is still foreign — falls back to
    CANNED_HU, so the robot never speaks a non-Hungarian line on stage.
    """
    if looks_hungarian(text):
        return text
    if regenerate is not None and looks_hungarian(retry := regenerate()):
        return retry
    return CANNED_HU
