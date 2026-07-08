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


def tokenize(text: str) -> list[str]:
    """Folded, stopword-stripped tokens (length > 1)."""
    return [t for t in _TOKEN.findall(_fold(text)) if len(t) > 1 and t not in STOPWORDS]
