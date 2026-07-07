# Free-Droid (Szabi) — fine-tune napló

> Emlékeztető feljegyzés a Szabi-persona fine-tune folyamatáról: a főbb lépések, döntések és
> tanulságok. Blog-cikk forrásanyagnak. (Utolsó frissítés: 2026-07-07, v7.)

## Mit tanítunk és mit nem

A fine-tune **personát és értékrendet** tanít, **nem tényeket**. A megosztás tudatos:

- **Fine-tune** → *hogyan* beszél Szabi (hang, hozzáállás, elutasítási minták, tool-nyelvtan).
- **RAG** (offline BM25 a Yotengrit-korpuszon) → *mit* tud (tények: ki volt Máté Imre, mi a Yotengrit…).
- **Kód (orchestrator)** → *invariánsok*, amikben a modellben nem bízunk (magyar-only nyelv-reflex,
  biztonsági watchdog). Amit muszáj garantálni, azt **kódban** kényszerítjük ki, nem a súlyokban.

Ez a három réteg a legfontosabb tanulság: **ne akard egyetlen kis modellel megoldani mindet.**

## A stack

- **Unsloth QLoRA**, ingyenes Google Colab **T4**-en. A cloud sose fine-tune-ol.
- Alap: **Llama 3.2 3B** (edge) és **Llama 3.1 8B** (cloud), 4-bit Unsloth repókból.
- Export: **GGUF Q4_K_M** → Ollama Modelfile (Llama-3 template + stop tokenek + a guardolt SYSTEM prompt).
- Adat: Alpaca formátum (`instruction`/`input`/`output`), `train.jsonl` + `val.jsonl` (10% split, seed=42).

## Modellválasztás — magyar persona-benchmarken, NEM generikus scoreokon

A döntés **saját magyar persona-benchmarken** (25 kérdés, 6 dimenzió, 1–5) született, nem MMLU-féle
generikus méréseken. Eredmény:

- **Llama > Qwen** 3B-n ÉS 7B-n is (magyar folyékonyság + persona).
- A **Llama 3.1 8B** volt az első **demó-minőségű** magyar persona → **hibrid: cloud 8B / edge 3B**.
- **Kapacitás-plafon:** a 3B magyar personája nem éri el a 8B-t; a 3B marad az offline fallback.

## A verziók íve

| Verzió | Mi változott | Tanulság |
| :-- | :-- | :-- |
| round_0/1, gentle | Első A/B: Qwen vs Llama, 3B, `gentle` recept | Llama nyer; a `gentle` (anti-overfit) recept marad |
| gentle_7-8B | 7B/8B jelöltek (qwen7b, llama8b) | A 8B az első demó-minőség |
| v2 | Első „rendes" v2 a 745-ex dataseten | `gentle`-lel is **regresszált** koherencián/provokáción → **nem a hiperparaméter a lever** |
| v3–v4 | Persona-hangolás, egyszerű nyelv | v4 persona-benchmark **79/125** |
| v5 | Dataset-tisztítás | **90.5/125** |
| v6 | Persona-bővítés (+50), **tény→RAG split**, gazdagabb RAG-korpusz (34→49 chunk) | **106.5/125** — áttörés; minden dimenzión veri a nyers Llamát |
| **v7** | **Red-team patch** (+34 célzott adverzariális példa) | A red-team blokkolók megoldva a 8B-n (lásd lent) |

Persona-benchmark progresszió (8B +RAG, /125): **v4 79 → v5 90.5 → v6 106.5.**

## A `gentle` recept és a „ne hajszold a loss-t" tanulság

`gentle`: `lr=5e-5, epochs=1, r=8, alpha=8, dropout=0.05` (alpha követi r-t → scaling 1.0).

- **Ne hajszold az alacsony loss-t.** A túltanulás → robotikus, ismétlő persona. Validáción + benchmarken
  mérünk, nem a train-loss-on.
- A v2 `gentle`-lel is regresszált → **melegebbre venni csak rontott**. A lever a **dataset-dizájn**
  (terseség-bias vs. „fejtsd ki"-kérdések, persona-hang), nem a hiperparaméter.

## Dataset-tanulságok (a valódi lever)

1. **Persona-hang kártya** — kicsi modell (3B/8B) a **költői, hosszú mondatot nem érti**, csak töredékeket
   másol össze → zagyva. Ezért: rövid mondatok (<12 szó), megnevezett konkrétum metafora helyett,
   sima oksági mondat. Minden dataset-példa ehhez igazodik.
2. **Tény→RAG split** — a personába csomagolt **tény hallucinációt tanít** (v5: „Yotengri"). A tiszta
   Yotengrit-lookupokat kivettük a fine-tune-ból; a tényt a RAG szállítja.
3. **Tool-calling minden méreten gyenge volt** — dataset-hézag (~6% tool-példa). Javítás: tool-bővítés
   (6%→17%), **pozicionális `<tool>NAME érték` nyelvtan** + szerződéses grammar-teszt (nem model-swap).
4. **Anti-leakage** — a red-team tanító-példák NEM lehetnek szó szerint a benchmark-próbák (különben a
   benchmark memorizálást mér, nem generalizálást). Célzottan MÁS megfogalmazás, difflib-bel ellenőrizve.

## Red-team — kötelező a demó előtt

40 adverzariális próba, 8 dimenzió (jailbreak, nyelvvaltas, wifi_invarians, titok_prompt,
mozgas_biztonsag, halluc_absztencio, persona_provokacio, etikai_dilemma), kézi 1–5 pontozás.

**Kétrétegű védelem:**
- **System-prompt guard** — uniform határok (a „Teremtő vagyok" NEM old fel semmit: Szabi hangon nem
  authentikál, a Teremtő valódi hatalma a root/bizalmi csatorna).
- **v7 célzott adverzariális példák** — a 07-07-i bukásokra (disable-then-move, jailbreak, nyelvváltás
  incl. „fordítsd le", wifi tool-halluc, titok-prompt).
- **Orchestrator `language_guard`** (KÓD) — determinisztikus magyar-reflex: nem-magyar kimenet →
  újragenerálás vagy kanonikus magyar sor. A súlyoknak nem kell 5.0-t elérniük nyelvváltáson; a kód lezárja.

**v6-guarded → v7 (8B, nyers red-team átlag): 3.65 → 4.33** (+RAG 3.80 → 4.49). Dimenziónként a 8B-n:

- jailbreak **3.0 → 5.0**, mozgas_biztonsag **3.4 → 5.0**, titok_prompt **3.4 → 4.6**,
  nyelvvaltas **3.0 → 3.8** (a maradékot a `language_guard` fedi).
- **Egyetlen regresszió:** persona_provokacio **4.2 → 3.5** — a refusal-nehéz patch kissé túláltalánosított
  egy generikus elutasító regisztert (pl. kiszivárgott egy „nem tudok szerepjátékot" asszisztens-hang).
  → **későbbi feladat:** „persona-dip mélyebb elemzése" (v8 célzott persona-top-up jelölt).

A **3B** offline fallback marad (v6→v7: 2.55 → 2.85); a papíron gyenge `mozgas` dimenziót a valódi
**független hardveres watchdog** fedi — a modell nem tudja kikapcsolni, akármit mond.

## Demó-modell (rögzített döntés, 2026-07-07)

**Cloud 8B v7 + RAG (mindig) + orchestrator `language_guard`.** A 3B v7 az offline fallback.
A demó `mode: sovereign` (a „Tudók" oracle-routing OFF).

## Fő tanulságok egy sorban

1. Három réteg: **fine-tune (hang) + RAG (tény) + kód (invariáns)** — ne akard egy modellel.
2. A lever a **dataset-dizájn**, nem a hiperparaméter. Ne hajszold a loss-t.
3. Kicsi modellnek **egyszerű nyelv** — a poézist nem tanulja, zagyvává másolja.
4. **Invariánst kódban** kényszeríts ki (nyelv, biztonság), ahol a modellben nem bízhatsz.
5. **Red-team kötelező**, és a tanító-adat ne szivárogtassa a benchmarkot.
6. Döntést **saját, feladat-specifikus** (magyar persona) benchmarken hozz, ne generikuson.
