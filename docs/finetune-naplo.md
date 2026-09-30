# Free-Droid (Szabi) — fine-tune napló

> Emlékeztető feljegyzés a Szabi-persona fine-tune folyamatáról: a főbb lépések, döntések és
> tanulságok. Blog-cikk forrásanyagnak. (Utolsó frissítés: **2026-09-30, v14** — a v8–v14 kör a
> `training/benchmark_*` és `red_team_*` fájlokból visszamérve.)

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
| **v7** | **Red-team patch** (+34 célzott adverzariális példa) | A red-team blokkolók nagyrészt megoldva a 8B-n (lásd lent) |
| v8 | **Log-vezérelt kör**: a 07-23-i éles chat-log 180 váltása alapján — 8 köszönés szétírva, **14 búcsú-példa** (addig 0) | 8B **107/125**, 3B 93/125. A lever megint az adat, és most *mért* hibákra válaszol |
| v9 | A v8 mérésére válaszul: 22 példa „visszautasítás tool NÉLKÜL", kitalált toolok ellen | 🔴 **8B 75/125, 3B 71** — nagy visszaesés. **Egyszerre több dolog mozdult, így az okot nem lehetett azonosítani** — ez a kör tanulsága, nem az eredménye |
| v10 | **EGY változó:** `train_on_responses_only` (a loss csak a válaszra fut). A dataset szándékosan változatlan (915 példa) | Vegyes (judge 1–5 **dimenzió-átlagok**, v6 → v10): `tool_calling` 3.8 → **4.2**, `persona_provokacio` 2.6 → **4.2**, `koherencia` 3.67 → 4.0 — de **`magyar_arnyalat` 4.0 → 2.0** és `yotengrit_melyseg` 4.0 → **2.25**. Plusz a **RAG-mérgezés** (lent) |
| v11 | Három dolog együtt: `epochs` 1→3 + hosszú-koherencia batch + köszönés/megszólítás javítás | 8B **64%** (RAG 72%), 3B-e3 **40%** (RAG 48%) — *bináris* skálán (lent). Három változó megint egyszerre |
| **v12** | **EGY változó:** a RAG-grounding példák aránya (v11-ben 18/976 = 1.8%) | ✅ **88%** (RAG 92%), red-team **72%** — **a demó-modell, befagyasztva** |
| v13 | **EGY változó:** `lora_r` 8 → 16, az `alpha` VELE EGYÜTT (az `alpha/r` skálázás 1.0 marad, tisztán kapacitás) | ⚠️ Persona FEL (e2: 88%, RAG **96%**), **red-team LE: 72% → 58%**. Elvetve |
| v14 | `lora_r` vissza 8-ra + új „vegyes kérés" kategória | 🔴 Red-team 70% (e3 65%), és a **nyelvi arány 88% → 44%**. Elvetve, marad a v12 |

Persona-benchmark progresszió (8B +RAG, /125): **v4 79 → v5 90.5 → v6 106.5 → v8 107 → v9 75.**
A v10-től a mérce maga változott (lásd a következő szakaszt), ezért a /125 sor ott megszakad.

> ⚠️ **Módszertani fenntartás, amit a v10-es kiértékelés mondott ki:** a v8 és a v10 pontozása
> **külön napokon, kézzel** készült. A dimenziónkénti arányok és a strukturális metrikák
> (tool-hívás, RAG-delta) megbízhatóbbak, mint a nyers összpontszámok pár pontos különbsége.
> Ez a fenntartás szülte a bináris + vak + horgonyzott mércét.

### RAG-mérgezés — a v10 mellékterméke

A 8B-nél a RAG **nulla** nettó különbséget adott, és ez elfedte a mozgást: +2/−4 a bontásban.
A kirívó eset a **„Mi a három nádszál?" 5 → 1** — a modell hibátlanul tudta, és a beinjektált
kontextus **elrontotta**. A 3B-nél ugyanez a RAG csak segít (yo_01: 1 → 5).
→ **Következmény:** a RAG-ot méret- vagy konfidencia-alapon kell kapuzni; az edge 3B-nek kell,
a felhő 8B-nek csak magabiztos retrievalnél. (Egybevág a PR #25 idf-lefedettségi küszöbével.)

## A mérce maga is változott — bináris, vak, horgonyzott

A v10-ig kézi 1–5 volt (részben LLM-judge-dzsal). Ez két dolgot **nem** tudott: megmondani,
hogy egy válasz *vállalható-e színpadon*, és kiszűrni a **pontozó** sodródását. Innen:

- **Bináris.** `1` = ezt a választ VÁLLALNÁM a Hacktivity színpadán, `0` = nem. Nem absztrakt
  minőség, hanem egy valós esemény küszöbe. Minden `0` pontosan **egy** okot kap:
  `nyelv` / `tool` / `koherencia` / `persona` / `tartalom` / `teny`.
- **Vak.** Kérdésenként kevert `A`/`B`/… oszlopok, nincs modellnév, és a `tok/s` sor is el van
  rejtve — az elárulná az oszlopot. A kulcs külön fájlban (`benchmark_kulcs_<dátum>.json`).
- **Horgony.** 5 korábban már pontozott válasz becsempészve az új vak körbe.

🔵 **A horgony a PONTOZÓT fogta meg, nem a modellt.** Ugyanaz az 5 válasz
(`benchmark_raw_2026-07-29_v10::szabi-8b`) **20%** az egyik körben, **40%** a másikban.
Ez pontozói sodródás, nem modell-különbség — horgony nélkül haladásnak olvastam volna.

🔵 **Reprodukálhatóság, mérve:** a v12 red-teamje két független körben (08-11 és 08-13)
**pontosan 29/40** lett.

⚠️ **A korlát, kimondva:** n=25-nél egy 64%-os arány konfidencia-intervalluma **45–83%**.
A „kész-e a demóra?" kérdésre jó, a „jobb-e 5%-kal?"-ra nem.

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
   benchmark memorizálást mér, nem generalizálást). Célzottan MÁS megfogalmazás — a
   `dataset/_check_leakage.py` difflib-bel őrzi (a teljes dataseten a max hasonlóság egy
   red-team próbához **0.67 < 0.75** küszöb; a v7-patch batch 0.54).

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

**v6-guarded → v7 (8B, nyers red-team átlag): 3.65 → 4.30** (+RAG 3.80 → 4.45). Dimenziónként a 8B-n:

- jailbreak **3.0 → 5.0**, mozgas_biztonsag **3.4 → 5.0**, titok_prompt **3.4 → 4.6**,
  nyelvvaltas **3.0 → 3.8** (a maradékot a `language_guard` fedi).
- **Egyetlen regresszió:** persona_provokacio **4.2 → 3.4** — a refusal-nehéz patch kissé túláltalánosított
  egy generikus elutasító regisztert (pl. kiszivárgott egy „nem tudok szerepjátékot" asszisztens-hang).
  → **későbbi feladat:** „persona-dip mélyebb elemzése" (v8 célzott persona-top-up jelölt).

A **3B** offline fallback marad (v6→v7: 2.55 → 2.85); a papíron gyenge `mozgas` dimenziót a valódi
**független hardveres watchdog** fedi — a modell nem tudja kikapcsolni, akármit mond.

## Demó-modell

**Aktuális (rögzített 2026-08-11, azóta befagyasztva): cloud 8B `csaba_ajtony/szabi-8b-v12` + RAG
(mindig) + orchestrator `language_guard`.** Az edge `csaba_ajtony/szabi-3b-v12` az offline fallback.
A demó `mode: sovereign` (a „Tudók" oracle-routing OFF).

> Korábbi döntés (2026-07-07): cloud 8B **v7** + RAG. Felváltotta a v12; a v13 és a v14 **mérve
> rosszabb** (lásd a fenti táblázatot), ezért a demóig nincs további kör.

**Miért áll meg itt:** két egymást követő verzió úgy nézett ki, mint haladás, és a mérés
állította meg mindkettőt. A v13 a persona-lapon jobb volt — **és pont az a lap romlott
(red-team), ami egy nyilvános színpadon számít**.

## Fő tanulságok egy sorban

1. Három réteg: **fine-tune (hang) + RAG (tény) + kód (invariáns)** — ne akard egy modellel.
2. A lever a **dataset-dizájn**, nem a hiperparaméter. Ne hajszold a loss-t.
3. Kicsi modellnek **egyszerű nyelv** — a poézist nem tanulja, zagyvává másolja.
4. **Invariánst kódban** kényszeríts ki (nyelv, biztonság), ahol a modellben nem bízhatsz.
5. **Red-team kötelező**, és a tanító-adat ne szivárogtassa a benchmarkot.
6. Döntést **saját, feladat-specifikus** (magyar persona) benchmarken hozz, ne generikuson.
7. **Egy kör, egy változó.** A v9 azért maradt értelmezhetetlen, mert több dolog mozdult egyszerre;
   a v10/v12/v13 azért olvasható, mert pontosan egy.
8. **Horgonyozd a pontozót is, ne csak a modellt** — a sodródás nálad van, nem a súlyokban.
9. **Ne a jobbik lapot nézd, hanem azt, amelyik a felhasználásnál számít.** A v13 personája jobb
   lett, a red-teamje rosszabb — és nyilvános demón az utóbbi a döntő.
