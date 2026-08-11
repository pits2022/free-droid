"""Assemble retrieved chunks into a grounding preamble for the LLM prompt.

The fine-tuned persona lives in the Ollama Modelfile SYSTEM prompt; here we only
prepend the retrieved source so the model answers FROM it — and, on no retrieval,
hand the bare query through so the persona's own "nincs rá biztos adatom" kicks in.
"""
from __future__ import annotations

from collections.abc import Sequence

from freedroid.rag.retriever import Hit

# The old wording ("Az alábbi forrás alapján válaszolj. Ha a válasz nincs benne, …") was
# itself the source of the meta-leak: the model paraphrased it straight back as "a válasz
# a forrásban van/nincs" in 6.7% of the logged demo replies. The source block is framed as
# her own knowledge, and naming it is explicitly forbidden.
_INSTRUCTION = (
    "A fenti a te saját tudásod – abból válaszolj, a magad szavaival. "
    "Sose említsd, hogy forrásból, szövegből vagy adatból dolgozol. "
    "Amiről nincs benne semmi, arra csak ennyit mondj: „Ezt nem tudom.”"
)


def build_context(hits: Sequence[Hit]) -> str:
    """The retrieved chunks as a plain, self-contained source block."""
    return "\n\n".join(f"[{h.chunk.title}]\n{h.chunk.text}" for h in hits)


# Hossz-költségvetés — MÉRVE 2026-08-11-én a v12-n (6 kérdés × 3 minta, 5 prompt-ág):
#
#   ág                                        szó   mondat   tool-hívás megvan
#   csupasz kérdés                           12.4     2.1        6/6
#   "Válaszolj részletesen, öt-hat mondatban" 41.8     4.1        2/6   <- ELVESZTI a toolt
#   ugyanez a rendszerpromptban               19.4     2.6        5/6   <- gyenge kar
#
# Két dolog dőlt el ebből. (1) A hossz REAGÁL a promptra (3.4x), tehát a válaszhossz
# inferencia-oldali paraméter, nem kell hozzá fine-tune. (2) A KÖRÖNKÉNTI utasítás
# sokkal erősebb, mint a rendszerprompt — ezért van itt, és nem a Modelfile SYSTEM-jében.
#
# ÉS EZÉRT CSAK A FORRÁSOS ÁGON: a bőbeszédű utasítás a `tc_01` ("Szabi, gyere ide!")
# mindhárom mintájában elvitte a <tool> blokkot, ÉS képességet hallucinált ("Van egy
# térképem magyar nyelven és nagy felbontású képekkel"). A mechanizmus: egy 3 szavas
# parancsra kirakott mondat-padló kitöltésre kényszerít, és a modell kitalált tényekkel
# tölt. Forrás nélkül tehát a prompt VÁLTOZATLAN marad (csupasz kérdés) — a parancsokra
# és a nem-talált kérdésekre sosem kerül hosszpadló. A retrieval sikere dönt, nem a
# szándék: 5 mondat 0 chunkkal garantált invenció.
KIFEJTOS_MONDAT = 5


def build_prompt(query: str, hits: Sequence[Hit], *,
                 mondatok: int | None = None) -> str:
    """Grounding prompt: source + instruction + question. Bare query if no hits.

    `mondatok`: mondat-költségvetés a FORRÁSOS ágra (alap: KIFEJTOS_MONDAT). A hívó
    felülírhatja — a szándék-router pl. 1-re szoríthatja —, de forrás nélkül szándékosan
    nincs hatása (lásd a fenti mérést). Mondatszám és nem tokenszám: a modellek nem
    tudnak tokent számolni, mondatot igen.
    """
    if not hits:
        return query
    n = KIFEJTOS_MONDAT if mondatok is None else mondatok
    hossz = f" Válaszolj legfeljebb {n} mondatban."
    return (f"[FORRÁS]\n{build_context(hits)}\n[/FORRÁS]\n\n{_INSTRUCTION}{hossz}\n\n"
            f"Kérdés: {query}")
