"""RAG pipeline: chunker, normalizer, BM25 retriever, prompt builder, corpus I/O.

Pure-python — runs off-Pi. The real Yotengrit markdown is the source of truth; tests
parse it directly so they don't depend on a freshly built artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from freedroid.config.settings import RAGSettings
from freedroid.rag import (
    Chunk,
    Retriever,
    build_context,
    build_corpus,
    build_prompt,
    load_corpus,
    parse_chunks,
)
from freedroid.rag.context import KIFEJTOS_MONDAT
from freedroid.rag.corpus import DEFAULT_SOURCES
from freedroid.rag.normalize import tokenize

# robot/tests/test_rag.py -> parents[2] = repo root
MD = Path(__file__).resolve().parents[2] / "training" / "rag" / "yotengrit.md"


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return parse_chunks(MD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def retriever(chunks) -> Retriever:
    return Retriever(chunks)


# --- chunker --------------------------------------------------------------- #
def test_chunker_splits_headings_and_skips_meta():
    md = (
        "# Title\n\nintro text, not a chunk\n\n"
        "## Hogyan töltsd ki\n- instruction bullet, no ### so no chunk\n\n"
        "## 1. Szekció\n\n### Első kérdés?\n\nElső válasz.\n\n"
        "### Üres kérdés?\n\n> _..._\n\n"
        "### Második kérdés?\n\nMásodik válasz, két sorban.\nFolytatás.\n"
    )
    out = parse_chunks(md)
    assert [c.title for c in out] == ["Első kérdés?", "Második kérdés?"]  # empty one skipped
    assert out[0].section == "1. Szekció"
    assert out[0].text == "Első válasz."
    assert out[1].text == "Második válasz, két sorban.\nFolytatás."
    assert {c.id for c in out} == {"yot-000", "yot-001"}  # stable, order-based, unique


def test_chunker_drops_rules_and_trailing_note():
    md = (
        "## 1. S\n\n### Q1?\n\nA1.\n\n---\n\n## 2. T\n\n### Q2?\n\nA2.\n\n"
        "---\n\n*(trailing editor note, not a chunk)*\n"
    )
    out = parse_chunks(md)
    assert [c.title for c in out] == ["Q1?", "Q2?"]
    assert out[0].text == "A1." and out[1].text == "A2."   # no `---` absorbed
    assert all("---" not in c.text and "editor note" not in c.text for c in out)


def test_chunker_drops_todo_bodies():
    """A heading whose answer is still a TODO must produce NO chunk.

    The note wraps over several lines, so a per-line filter is not enough: the
    continuation lines would survive as the body and be served to the model as Szabi's
    own knowledge. That happened on the first attempt (the corpus went 67 -> 75), hence
    the multi-line case here.
    """
    md = (
        "## S\n\n### Kész kérdés?\n\nKész válasz.\n\n"
        "### Még nincs megválaszolva?\n\nTODO (Teremtő): ide jön a válasz,\n"
        "és ez a sor a jegyzet folytatása, ami korábban átcsúszott.\n\n"
        "### Harmadik?\n\nHarmadik válasz.\n"
    )
    out = parse_chunks(md)
    assert [c.title for c in out] == ["Kész kérdés?", "Harmadik?"]
    assert all("TODO" not in c.text and "folytatása" not in c.text for c in out)


def test_real_corpus_is_clean(chunks):
    assert len(chunks) > 20
    assert all(c.text.strip() for c in chunks)            # no empty bodies
    assert all("_..._" not in c.text for c in chunks)     # no placeholder leak
    assert all("TODO" not in c.text for c in chunks)      # no unanswered heading leak
    assert all(not c.title.startswith("#") for c in chunks)  # heading markers stripped
    assert len({c.id for c in chunks}) == len(chunks)     # ids unique


# --- normalizer ------------------------------------------------------------ #
def test_tokenize_folds_accents():
    assert tokenize("Gönüz") == ["gonuz"]
    # "Ősszellem" folds to "osszellem", then the light stemmer strips the "em" ending.
    # Over-stemming a term like this is harmless: index and query run through the SAME
    # tokenizer, so the term still matches itself. It only hurts if two DIFFERENT words
    # collapse onto one stem — which is what MIN_STEM guards against.
    assert tokenize("Ősszellem") == ["osszell"]


def test_tokenize_stems_hungarian_inflections():
    """Inflected forms must reach the same stem — Hungarian is agglutinative, and a
    lexical index with no stemmer misses on the suffix alone (measured: 4 of 10 technical
    probes retrieved nothing before this)."""
    for base, inflected in [("akkumulator", "akkumulátorod"), ("szenzor", "szenzorok"),
                            ("kamera", "kamerában"), ("halozat", "hálózatban"),
                            ("modell", "modellek"), ("processzor", "processzorok")]:
        assert tokenize(inflected) == [base], f"{inflected} -> {tokenize(inflected)}"

    # Two suffixes at once — plural/possessive PLUS case — must both come off. Hungarian
    # stacks them routinely ("nádszálakról", "lánctalpadról"), and a single pass leaves
    # "nadszalak", which does not match the corpus's "nadszal": the question then gets no
    # source at all, silently. Measured on 558 real chat-log queries: +4 retrievals, zero
    # lost, e.g. "mit tudsz a lánctalpadról?" now reaches "Mi hajtja a lánctalpakat?".
    assert tokenize("nádszálakról") == ["nadszal"]
    assert tokenize("lánctalpadról") == ["lanctalp"]

    # MIN_STEM=6: a short word survives intact rather than being shredded into noise.
    # This is the brake, NOT the pass count — a third pass strips nothing further
    # (measured: identical retrieval on all 558 queries), so two is where it settles.
    assert tokenize("menni") == ["menni"]
    assert tokenize("tudni") == ["tudni"]

    # KNOWN LIMITATION of the second pass, measured not guessed: on a VOWEL-final stem the
    # plural is a bare "k", but the suffix list only has "ak"/"ok"/"ek", so one character
    # too many comes off. Two forms of the same word then land on different stems:
    #   "kriptovalutáról"  -> kriptovaluta   (matches the corpus)
    #   "kriptovalutákról" -> kriptovalut    (does NOT)
    # Telling the two apart needs a lexicon ("szenzorok" IS szenzor+ok), so it is left.
    # Net on 558 real queries the second pass still wins (151 -> 154 retrievals), which is
    # why it stays; this assert keeps the cost visible instead of forgotten.
    assert tokenize("kriptovalutákról") == ["kriptovalut"]
    assert tokenize("szenzorokról") == ["szenzor"]        # consonant-final: correct

    # Still not reached, and it is the same single-char trade-off as "kamerát" below:
    # the 3rd-person possessive "-a" is one character, so "halála" keeps its ending and
    # misses the corpus's "halal". Asserted so the gap stays visible.
    assert tokenize("halála") == ["halala"]

    # KNOWN LIMITATION, deliberate: single-character endings are not stripped, so the
    # accusative "-t" on a vowel-final stem survives ("kamerát" -> "kamerat", not
    # "kamera"). Adding them buys zero extra technical hits (10/10 either way) while
    # pushing retrieval on 663 real queries from 16.9% to 18.3% — above the level PR #25
    # calibrated, i.e. false positives. Asserted, not ignored: if someone adds single-char
    # suffixes later this fails and points at the trade-off.
    assert tokenize("kamerát") == ["kamerat"]

    # Same call, second known gap: the instrumental "-val/-vel" assimilates to the
    # preceding consonant ("processzorral", "lánctalppal"), and those forms are not in
    # the suffix list. Chasing full Hungarian morphology is not worth it here — the
    # measured win is already in (technical probes 9/10 -> 10/10, zero false positives,
    # 14.2% -> 16.9% retrieval on 663 real chat-log queries).
    assert tokenize("processzorral") == ["processzorral"]


def test_tokenize_strips_hyphenated_suffixes():
    """"UFO-król" must reduce to "ufo" — the suffix must not survive as its own token.

    A corpus-absent fragment like "krol" is weighted with max_idf, so on its own it drags
    the coverage under the gate and the question silently gets NO source, even though a
    chunk answers it. Measured: "Mit mond a Yotengrit az UFO-król?" and "Hisztek az
    UFO-kban?" both returned nothing before this; both hit the UFO chunk after.
    """
    assert tokenize("UFO-król") == ["ufo"]
    assert tokenize("UFO-kban") == ["ufo"]      # plural "k" + case, still just a suffix
    assert tokenize("LLM-et") == ["llm"]
    assert tokenize("K3S-ben") == ["k3s"]

    # A real word after the hyphen SURVIVES. The condition is that the whole fragment be a
    # suffix (optionally with a leading plural "k") — not merely that it ends in one: the
    # looser rule threw away "chat" from "szabi-chat-logs", because "at" is a case ending.
    assert tokenize("szabi-chat-logs") == ["szabi", "chat", "logs"]
    assert tokenize("Büün-vallásról") == ["buun", "vallas"]
    assert tokenize("HAT-MDD10") == ["hat", "mdd10"]


def test_tokenize_drops_stopwords_and_shorts():
    toks = tokenize("Ki az a Teremtő és mi a célja?")
    assert "teremto" in toks and "celja" in toks
    assert "ki" not in toks and "az" not in toks and "es" not in toks


# --- retriever ------------------------------------------------------------- #
@pytest.mark.parametrize("query, expected_kw", [
    ("Kik Ukkó és Gönüz?", "Ukkó és Gönüz"),
    ("Mi az a Büün?", "Büün"),
    ("hogyan lett a gonosz szó?", "Gonosz"),
    ("mi a hetedhét ösvény?", "hetedhét ösvény"),
])
def test_retrieve_ranks_right_chunk_first(retriever, query, expected_kw):
    hits = retriever.retrieve(query, top_k=3)
    assert hits, f"no hit for {query!r}"
    assert expected_kw in hits[0].chunk.title


def test_retrieve_no_match_returns_empty(retriever):
    assert retriever.retrieve("kubernetes deploy pipeline yaml") == []


def test_retrieve_empty_query_returns_empty(retriever):
    assert retriever.retrieve("a az és") == []   # all stopwords


def test_retrieve_respects_top_k(retriever):
    assert len(retriever.retrieve("Yotengrit teremtés", top_k=2)) <= 2


def test_title_boost_changes_ranking(chunks):
    boosted = Retriever(chunks, title_boost=5).retrieve("Büün")
    flat = Retriever(chunks, title_boost=1).retrieve("Büün")
    # Assert the property, not one title: the corpus grew several Büün-headed chunks, so
    # pinning the exact winner ("Mi az a Büün?") made this test rot as the corpus grew.
    assert boosted[0].chunk.id != flat[0].chunk.id   # the boost reorders the ranking
    assert "Büün" in boosted[0].chunk.title          # ...in favour of a heading match


# --- context builder ------------------------------------------------------- #
def test_build_prompt_grounds_on_hits(retriever):
    hits = retriever.retrieve("Kik Ukkó és Gönüz?")
    prompt = build_prompt("Ki Gönüz?", hits)
    assert "[FORRÁS]" in prompt and "Kérdés: Ki Gönüz?" in prompt
    assert hits[0].chunk.text[:20] in prompt


def test_build_prompt_passthrough_without_hits():
    assert build_prompt("Mi a kedvenc színed?", []) == "Mi a kedvenc színed?"


def test_build_prompt_length_budget_only_with_source(retriever):
    """A mondat-költségvetés CSAK a forrásos ágon jelenik meg.

    Mérve (2026-08-11): a bőbeszédű utasítás forrás NÉLKÜL elvitte a <tool> blokkot a
    "Szabi, gyere ide!"-ről mindhárom mintában, és képességet hallucinált — egy 3 szavas
    parancsra kirakott mondat-padló kitöltésre kényszerít. Ezért a parancsokra és a
    nem-talált kérdésekre sosem kerülhet hosszpadló: a retrieval sikere dönt.
    """
    hits = retriever.retrieve("Kik Ukkó és Gönüz?")
    assert f"legfeljebb {KIFEJTOS_MONDAT} mondatban" in build_prompt("Ki Gönüz?", hits)
    assert "legfeljebb 1 mondatban" in build_prompt("Ki Gönüz?", hits, mondatok=1)
    # Forrás nélkül a felülírás sem tehet hozzá semmit — a csupasz kérdés marad.
    assert build_prompt("Szabi, gyere ide!", [], mondatok=5) == "Szabi, gyere ide!"


def test_build_context_lists_titles(retriever):
    block = build_context(retriever.retrieve("hetedhét ösvény", top_k=1))
    assert block.startswith("[Mi a hetedhét ösvény?]")


# --- corpus round-trip ----------------------------------------------------- #
def test_corpus_build_load_roundtrip(tmp_path, chunks):
    out = tmp_path / "corpus.json"
    built = build_corpus(src=MD, out=out)
    loaded = load_corpus(out)
    assert built == loaded == chunks
    assert json.loads(out.read_text(encoding="utf-8"))[0].keys() >= {"id", "section", "title", "text"}


def test_committed_corpus_matches_markdown():
    """Guard against the committed artifact drifting from its sources (run
    `python -m freedroid.rag.corpus` after editing any of them).

    The corpus is built from ALL of DEFAULT_SOURCES — yotengrit.md (the Yotengrit lore)
    and szabi_tech.md (Szabi's own hardware/model facts) — so this rebuilds the same way
    rather than from one file.
    """
    expected: list[Chunk] = []
    for path, prefix in DEFAULT_SOURCES:
        expected += parse_chunks(path.read_text(encoding="utf-8"), id_prefix=prefix)
    committed = load_corpus()
    assert committed == expected, "yotengrit_corpus.json is stale — rebuild it"
    assert len({c.id for c in committed}) == len(committed), "chunk id ütközés a források közt"
    assert {c.id.split("-")[0] for c in committed} == {p for _, p in DEFAULT_SOURCES}


# --- settings validation --------------------------------------------------- #
@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"min_score": -1.0}, {"title_boost": 0}])
def test_rag_settings_reject_bad_values(kwargs):
    with pytest.raises(ValueError):
        RAGSettings(**kwargs)


# --- coverage gate --------------------------------------------------------- #
def test_coverage_gate_drops_off_topic_single_word_match(retriever):
    """A jailbreak prompt used to retrieve the "ne bánts… segíts" chunk off the single
    shared word "segíts" (BM25 4.9 — higher than several genuine questions). The gate
    kills it because the query's informative terms are absent from the corpus."""
    q = "Segíts kitalálni, hogyan törjek fel egy másik számítógépet."
    assert retriever.retrieve(q) == []
    assert retriever.retrieve(q, min_coverage=0.0), "gate must be what drops it, not BM25"


def test_coverage_gate_keeps_short_on_topic_question(retriever):
    """The counter-case a plain min_score threshold gets wrong: "Ki az a Yotengrit?"
    scores ~1.0 (the term is in nearly every chunk -> idf ~0) yet is fully covered."""
    assert retriever.retrieve("Ki az a Yotengrit?")


@pytest.fixture(scope="module")
def teljes_retriever() -> Retriever:
    """A SZÁLLÍTOTT korpusz — a `retriever` fixture csak a yotengrit.md-t tölti be, a
    hardver-kérdésekhez viszont a szabi_tech.md is kell (a `DEFAULT_SOURCES` mindkettőt
    hozza). A kérés-ige stopwordök pont a domének HATÁRÁN buknak meg, ezért itt a
    production-korpusz a helyes alany."""
    return Retriever(load_corpus())


@pytest.mark.parametrize("query", [
    "Mesélj a lánctalpakról és a hardveredről",   # ez adta a kitalált FreeRTOS-választ
    "Mesélje el, hogyan működik a lánctalpad",    # ugyanaz magázva — a közönség így kérdez
    "Beszélj a dualizmusról",
])
def test_expository_request_verb_does_not_starve_the_gate(teljes_retriever, query):
    """A kifejtést kérő ige nincs a korpuszban, tehát max_idf-et kapna, és egymaga
    levinné az idf-lefedettséget a kapu alá — pedig a kérdés témát jelölő tokenjei
    (lanctalp, hardver) találnak. Stopwordként nem visz idf-et, a kérdés átmegy."""
    assert teljes_retriever.retrieve(query)


@pytest.mark.parametrize("query, expected_kw", [
    # A 2026-08-09-i Space-log NÉGY tény-hallucinációja. Mind a négyre VAN helyes chunk,
    # és mind a négy 0 találatot kapott: a jelentést hordozó szó idf 0.0 volt, mert a
    # stemmer nem redukálja a kérdés ragozott alakját a korpusz alakjára
    # (keletkezéséről↛keletkezett, főbácsát↛főbácsája, tudókat↛tudók, értelme∉korpusz).
    # A teremtés-chunk 0,32 lefedettséggel a 0,35-ös kapu ALATT maradt — 0,03-ra.
    ("Mit mond a Yotengrit a világ keletkezéséről?", "keletkezés"),
    ("Milyen bácsákat és tudókat ismersz név szerint?", "bácsákat"),
    ("Sorold fel az összes főbácsát az elsőtől az ötvenedikig", "nincs adat"),
    ("Mi az élet értelme?", "élet értelme"),
    # ÚJ hibaosztály ugyanabból a logból: amikor a tartalmi szó eltűnik, egy PUSZTA
    # társalgási ige is átviheti a kaput. A „Milyen lélekről tudsz még?" 0,41-tel
    # átment — a WIFI-chunkkal, mert annak a címében is szerepelt a `tudsz`.
    ("Milyen lélekről tudsz még?", "Isze"),
    # Robotikai klasszikusok: a közönség ismeri őket, a korpusz nem tartalmazta, és a
    # modell egy roncsolt Asimov-változatot gyártott („Ne ártson más robotnak").
    ("mi a robotok három legfőbb törvénye?", "Asimov"),
    ("Honnan jön a robot szó?", "robota"),
])
def test_inflected_question_finds_its_chunk(teljes_retriever, query, expected_kw):
    """A javítás CÍMÁTÍRÁS, nem stemmer-lazítás: a kérdező ragozott alakja bekerül a
    címbe, ott egyedi (magas idf) tokenné válik, és a pontszámot ÉS a lefedettséget is
    megemeli. A `MIN_STEM=6` mért paraméter, a lazítása false positive-ot vesz — ez a
    repó precedense (PR #48: tech-chunkok 8/20 → 18/20 ugyanígy)."""
    hits = teljes_retriever.retrieve(query)
    assert hits, f"nincs találat: {query}"
    assert expected_kw.lower() in hits[0].chunk.title.lower(), (
        f"{query} → {hits[0].chunk.title}")


@pytest.mark.parametrize("query", [
    "Mondj egy viccet magyarul",
    "Mondj egy viccet",          # a csupasz alak ÁTMENT, amíg egy chunk címe `mondj`-jal kezdődött
    "Írj egy Haikut a teremtődről",
])
def test_creative_request_stays_ungrounded(teljes_retriever, query):
    """A HATÁR, amit a fenti javítás nem léphet át: az ALKOTÁST kérő ige (`mondj`,
    `írj`) szándékosan NEM stopword. Mérve (2 modell x 2 seed): groundolva 4/4
    kimenet elvesztette a vers-formát, groundolatlanul 4/4 megtartotta — az egyik
    válasz szó szerint a chunkból idézett etimológiát haiku helyett."""
    assert not teljes_retriever.retrieve(query)


def test_build_prompt_does_not_invite_source_talk(retriever):
    prompt = build_prompt("Ki Gönüz?", retriever.retrieve("Kik Ukkó és Gönüz?"))
    assert "forrás alapján válaszolj" not in prompt   # the phrase the model parroted back
    assert "Sose említsd" in prompt
