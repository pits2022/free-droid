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
    # KIFEJTÉST kérő felszólítások. Ezek nem témát jelölnek, hanem a kérés formáját —
    # viszont ismeretlen tokenként MAGAS idf-et kapnak, és egymaga leviszik az
    # idf-lefedettséget a kapu alá. Mérve a 673 valódi chat-kérdésen: a
    # "Mesélj a lánctalpakról és a hardveredről" ÜRES találatot adott, pedig a
    # szabi_tech.md válaszol rá — és a 2026-08-08-i chatben pontosan erre jött a
    # kitalált "FreeRTOS"/"4x4-es modell" válasz.
    #
    # A LISTA SZÁNDÉKOSAN CSAK KIFEJTŐ IGÉ: a "mondj", "írj", "válaszolj" KIMARAD.
    # Azok ALKOTÁST kérnek (vicc, vers, haiku), és azokat a kapunak dobnia KELL —
    # méréssel: velük együtt a "Mondj egy viccet magyarul" és az "Írj egy Haikut a
    # teremtődről" is [FORRÁS]-t kapott, azaz a haiku tanítást mondott volna fel.
    "mesélj", "meséld", "magyarázd", "magyarázz", "beszélj", "sorold",
    "ismertesd", "foglald",
    # MAGÁZÓ alakok. A konferencia közönsége jó eséllyel magázza a robotot, és a
    # tegező listától eltérően ezeket a stemmer NEM kapja el mellékesen (a `-jen`/
    # `-jon` végű `meséljen`/`beszéljen` kiesik, a `-ja`/`-je` végű `mesélje`/
    # `magyarázza` nem). Mérve: "Magyarázd el, hogyan működik a lánctalpad" -> tech-009,
    # ugyanaz magázva -> ÜRES. Korpusz-ütközés nincs (az "összefoglalja" külön token).
    "mesélje", "magyarázza", "sorolja", "ismertesse", "foglalja",
}
STOPWORDS = frozenset(_fold(w) for w in _RAW_STOPWORDS)

_TOKEN = re.compile(r"[0-9a-z]+(?:-[0-9a-z]+)*")


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
#
# 2026-08-11: a TŐ-KONZISZTENCIA mérése (alapalak vs ragozott alak ugyanarra a tőre
# essen) új sort tett a táblába. A mérce ehhez KELLETT: a fenti két műszer egyike sem
# látja a token-szintű rombolást, mert a chat-arány csak azt számolja, kap-e a kérdés
# LEGALÁBB EGY chunkot — egy elrontott token a többi szó mellett ritkán viszi nullára.
#
#   config                       tő-pár   10+10 próba   968 chat-kérdés
#   alap                          8/15      20/20 / 6/10     25.6%
#   + többes birtokos (-aid…)    11/15      20/20 / 7/10     25.4%   <- EZ
#   „-ra/-re ki, -a/-e be"        2/15      20/20 / 8/10     25.4%   <- ELVETVE
#
# Az utolsó sor a tanulság: az `architektúra` (alapalak `architektu`, birtokos alak
# `architektur`) megjavítható a `-ra`/`-re` kivételével és az egykarakteres `-a`/`-e`
# felvételével — de az ÁRA hét elromlott pár (`nádszálra`, `kamerára`, `memóriára`,
# `lánctalpra`, `hardverre`, `tudásra`, `szabadságra` egyike sem egyezik többé az
# alapalakjával). A chat-arány ezt NEM mutatta (25.4% vs 25.6%), tehát mérce nélkül
# beszállt volna a kódba. Ne próbáld újra e nélkül a próba nélkül.
#
# Az egykarakteres ragok külön is újramérve: NULLA plusz találat, ahogy korábban.
MIN_STEM = 6
_SUFFIXES = (
    # Többes birtokos EGY LÉPÉSBEN. Két lépésben nem jön ki: a `szenzoraid` -> `-id` ->
    # `szenzora` -> `-ra` -> `szenzo`, azaz a `-ra` beleeszik a tőbe. Egységként a
    # `szenzoraid` -> `szenzor`, ami egyezik az alapalakkal. Ezért ÁLL ELÖL: a lista
    # sorrendje dönt, és a rövidebb `-id`/`-ra` elvinné előle.
    "aitok", "eitek", "jaid", "jeid", "aink", "eink",
    "aid", "eid", "aim", "eim", "ait", "eit",
    "otok", "etek", "atok", "unk", "juk",                         # possessive (plural)
    "bol", "rol", "tol", "hoz", "hez", "ban", "ben",              # case
    "nak", "nek", "val", "vel", "ert", "kent",
    "ba", "be", "ra", "re", "ig", "on", "en", "un", "ok", "ak", "ek",
    "od", "ed", "ad", "id", "ja", "je", "im", "am", "em",         # possessive (singular)
    "at", "et", "ot", "ut",                                       # accusative
)


# Két menet, mert a magyarban a többes szám ÉS a rag egyszerre áll a szón:
# "nádszálakról" -> nadszalak -> nadszal. Egy menettel a "nadszalak" nem talál rá a
# korpusz "nadszal"-jára, és a kérdés némán forrás nélkül marad. Kettőnél megáll:
# a MIN_STEM=6 korlát a fék, nem a menetszám — három menet ugyanezen a korláton
# amúgy sem vágna többet, viszont minden további menet a hibás vágás esélyét viszi.
_MENETEK = 2


def _stem(token: str) -> str:
    for _ in range(_MENETEK):
        for suf in _SUFFIXES:
            if token.endswith(suf) and len(token) - len(suf) >= MIN_STEM:
                token = token[: -len(suf)]
                break
        else:
            return token
    return token


# A kötőjel után álló darab lehet TOLDALÉK, nem szó: "UFO-król" -> ufo + krol. A `krol`
# sehol nincs a korpuszban, tehát max_idf-et kap, és egymaga leviszi a lefedettséget a
# kapu alá — a kérdés NÉMÁN forrás nélkül marad, pedig van rá chunk (mérve: az „UFO-król"
# és a „Hisztek az UFO-kban?" is üres találatot adott).
#
# A feltétel SZIGORÚ: a darab EGÉSZE legyen rag, legfeljebb egy többes „k"-val az élén
# ("krol" = k + rol, "kban" = k + ban). A lazább „ragra VÉGZŐDIK és rövid" szabály a
# „szabi-chat-logs" közepéből kidobta a „chat"-et (az `at` rag), ami valódi szó.
def _kotojel_bont(szo: str) -> list[str]:
    """Kötőjeles szó darabjai, a toldalék-jellegű farok nélkül."""
    if "-" not in szo:
        return [szo]
    darabok = szo.split("-")
    ki = [darabok[0]]
    for d in darabok[1:]:
        rag = d in _SUFFIXES or (d.startswith("k") and d[1:] in _SUFFIXES)
        if not rag:
            ki.append(d)
    return ki


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
    for szo in _TOKEN.findall(_fold(text)):
        for raw in _kotojel_bont(szo):
            if len(raw) < 2 or raw in STOPWORDS:
                continue
            stemmed = _stem(raw)
            if len(stemmed) > 1 and stemmed not in STOPWORDS:
                out.append(stemmed)
    return out
