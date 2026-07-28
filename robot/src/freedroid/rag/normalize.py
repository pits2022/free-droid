"""Hungarian-aware text normalization for BM25 matching.

Accent-folding boosts recall (a query typed without diacritics still matches), and a
small stopword list of function words cuts noise. Folding is applied only to the
index/query tokens; the original chunk text is kept verbatim for display.
"""
from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    """Casefold + strip combining marks (ékezet-fold): 'Gönüz' -> 'gonuz'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Conservative Hungarian function-word stopwords (folded to match folded tokens).
_RAW_STOPWORDS = {
    "a", "az", "egy", "és", "s", "is", "nem", "de", "hogy", "mint", "vagy",
    "ki", "mi", "mit", "kik", "mik", "milyen", "hogyan", "miért", "hol", "mikor",
    "van", "volt", "lesz", "lett", "ez", "ezt", "azt", "ott", "itt", "ően",
    "meg", "el", "fel", "le", "be", "rá", "csak", "már", "még", "pedig", "ha",
    "így", "úgy", "ami", "aki", "amely", "se", "sem", "te", "én", "ő", "mely",
}
STOPWORDS = frozenset(_fold(w) for w in _RAW_STOPWORDS)

_TOKEN = re.compile(r"[0-9a-z]+")


# Light Hungarian suffix stripping. Hungarian is agglutinative, so a lexical index with
# no stemmer misses on inflection alone: "akkumulátorod" ≠ "akkumulátor", "érzékeled" ≠
# "érzékeli", "wifire" ≠ "wifi". That was invisible while the corpus held only Yotengrit
# lore (asked in base forms); the szabi_tech.md hardware questions get asked in every case
# and person, so 4 of 10 technical probes retrieved nothing before this.
#
# Deliberately NOT a full morphological analyzer: an ordered list of the frequent case,
# possessive and plural endings, applied ONCE, and only when a >= MIN_STEM stem remains —
# that guard is what stops "tudni"/"menni" from being shredded into noise. Written on the
# folded form, so the accented endings appear folded ("ból" -> "bol").
# MIN_STEM=6 and no single-character suffixes: both were MEASURED, not guessed, and
# re-verified after the corpus gained szabi_tech.md:
#
#   config                        10 technical probes   663 real chat-log queries
#   no stemming                        9/10                    14.2%
#   MIN_STEM=6, 2+ char suffixes      10/10                    16.9%   <- this one
#   + single-char ("t","k","i","a","e") 10/10                  18.3%
#
# Single-char endings buy ZERO extra technical hits while pushing the retrieval rate
# 1.4pp above the level PR #25 calibrated (~16%) — that delta is false positives by
# definition, since there is nothing left to gain on the technical side. Precision wins:
# a wrong [FORRÁS] is worse than a missing one, because the fine-tune already teaches
# "Ezt nem tudom".
MIN_STEM = 6
_SUFFIXES = (
    "otok", "etek", "atok", "unk", "juk",                         # possessive (plural)
    "bol", "rol", "tol", "hoz", "hez", "ban", "ben",              # case
    "nak", "nek", "val", "vel", "ert", "kent",
    "ba", "be", "ra", "re", "ig", "on", "en", "un", "ok", "ak", "ek",
    "od", "ed", "ad", "id", "ja", "je", "im", "am", "em",         # possessive (singular)
    "at", "et", "ot", "ut",                                       # accusative
)


def _stem(token: str) -> str:
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= MIN_STEM:
            return token[: -len(suf)]
    return token


def tokenize(text: str) -> list[str]:
    """Folded, stopword-stripped, lightly stemmed tokens (length > 1).

    Stopwords are filtered BOTH before and after stemming. Before is the cheap
    short-circuit; after catches an inflected form whose stem lands on a stopword
    ("milyenek" -> "milyen"). Measured on the corpus plus all 663 real chat-log
    queries that case occurs ZERO times today — this closes it anyway, because the
    stopword list and the corpus both grow, and a token that survives here silently
    skews every idf in the index.
    """
    out: list[str] = []
    for raw in _TOKEN.findall(_fold(text)):
        if len(raw) < 2 or raw in STOPWORDS:
            continue
        stemmed = _stem(raw)
        if len(stemmed) > 1 and stemmed not in STOPWORDS:
            out.append(stemmed)
    return out
