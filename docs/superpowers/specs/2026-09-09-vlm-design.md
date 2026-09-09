# VLM — Szabi és a kamerakép

*Terv, 2026-09-09. A `docs/free-droid.md` §„Nyitva hagyott" tételének kibontása.*

## 1. Miért, és mi a valódi probléma

**A megoldandó probléma NEM a hiányzó látás, hanem a hazugság.** A 2026-08-28-i élő
menetben a „Nézz körül a kameráddal" erre futott:

> „Körben nézek, Teremtőm, de nem látom semmit. A kamera szürke, feketéje áthatolhatatlan.
> Nem tudom megmondani, milyen falak vannak ott."

Az első fele igaz, a második **kitalált vizuális leírás**. Ha a színpadon valaki
megkérdezi, hogy „mit látsz?", Szabi találni fog valamit — és ez a kockázat a látástól
FÜGGETLENÜL fennáll. Ezért:

> **A dataset/prompt munka (WP4) akkor is elvégzendő, ha a VLM belefér.** Nem tartalék
> ág: a VLM sem hoz be minden kérdést (letakart lencse, rossz fény, „mi van mögötted?"),
> és minden ilyen kérdésre ma konfabuláció a válasz.

**A mai állapot, mérve.** A kamera **csak aktuátor**: a `PanTiltCamera` `pan`/`tilt`/
gesztust tud, és soha nem olvas képkockát; a `health.check_camera` csak azt nézi, létezik-e
`/dev/video*`. A modellek szövegesek, sehol nincs multimodális út. A webkamera valódi
szerepe eddig a **mikrofonja** volt (2026-08-15).

## 2. Hatókör

**Benne van:** egy képkocka → felhős VLM → nyers leírás → a 8B mondja ki Szabi hangján.
Plusz egy **v15 fine-tune kör**, amibe a Teremtő teljes tapasztalat-listája bekerül.

**Nincs benne** (szándékosan, marad hangos `NotImplementedError`):
`move(mode=approach_speaker)` és `follow_speaker`. Ezek valós idejű képhurkot kívánnának
a ~139 ms-os alagúton át, saját biztonsági kérdésekkel a watchdog mellett. Külön kör.

**Nincs benne:** VLM az edge-en. A 3B már így is a lassú ág, egy 2B VLM mellé nem fér el
8 GB-ban valós időben. **A látás csak felhős — és ez jó így**, mert a hiánya épp az őszinte
ágat (WP4) kényszeríti ki, ami amúgy is kell.

## 3. A négy döntés (a Teremtő, 2026-09-09)

| # | Döntés | Indok |
| :- | :- | :- |
| 1 | **Leírás + saját v15 fine-tune kör** | A navigáció külön kör; a v15-be „az eddigi összes tapasztalat" bekerül, nem csak a VLM-specifikus. |
| 2 | **Két lépés: a VLM leír, a 8B mondja ki** | A VLM cserélhető marad, a persona egy helyen él, és a v15 a SZÖVEGES 8B-t tanítja — nem kell képi dataset. Szerkezetileg ugyanaz, mint az `oracle/` tervezett két lépése. |
| 3 | **Az orchestrátor dönt, nincs új tool** | A RAG-routing mintája. A mért tool-gyengeség (kitalált `action` értékek, hiányzó irány) így nem tud elrontani semmit; a `KNOWN_TOOLS` változatlan marad. |
| 4 | **A VLM nyelve mérésből dől el (WP0)** | Mindkét oldalon mért kockázat: az angol blokk a nyelv-regresszió (88% → 44%) felé tolhat; a magyar leírás minősége viszont esik, és abból a 8B magabiztos hazugságot épít. |

## 4. Architektúra

### 4.1 Hol fut a VLM — a MEGLÉVŐ felhős Ollamában, második modell-tagként

Az `/api/generate` fogad `images: [base64]` mezőt, tehát a VLM **nem új szolgáltatás**:
nincs új port, systemd unit, tűzfal-szabály vagy Ansible role, és a `FallbackLLMClient`
próba-mintája (`/api/tags`, `korben_elerhetetlen`) változtatás nélkül igaz rá. Az
`ai_stack` role már `ollama pull`-oz — egy tag jön hozzá.

⚠️ **A WP0 első két perce ezt IGAZOLJA, nem feltételezi:** hogy az `images` mező a
telepített Ollama-verzióval és a választott modell-taggel tényleg működik. A mai
`keep_alive`-hiba pont ilyen volt — az érték helyes, a TÍPUSA nem, és a hiba safe
mode-nak látszott. Ugyanide tartozik a **névtér**: a modell-tag itt SZÓ SZERINT az, amit
az Ansible húz (a `csaba_ajtony/szabi-3b-v12` rövidítése 404-et ad), tehát a
`VisionSettings` és az `ai_stack/defaults/main.yml` együtt mozog.

**Elvetve — külön VLM-szerver** (vLLM / llama.cpp `mtmd`), a `whisper-server` mintájára:
szerkezetileg működne, de megismételné a whisper CUDA-arch fájdalmat (a `whisper_cuda_arch`
körüli mérések és a rögzített commit nem véletlenek), új porttal, unittal és
health-checkkel. **Ez a tartalék terv**, ha a WP0 szerint az Ollamában elérhető
vision-modellek nem elég jók.

**VRAM, 20 GB-on (RTX 4000 Ada, `tor1`):** 8B Q4_K_M (~6) + whisper large CUDA (~4) +
2-7B VLM (~4-8). Elfér, de **nem bőven** — a WP0 egyik mérendő száma, hogy a három modell
EGYSZERRE bent van-e, mert a demón mindhárom kell.

### 4.2 Adatfolyam egy körben

```
FIGYELJ (kattintó)
  -> probe_mod.uj_kor()          # a kör-hatókörű elérhetőség-cache nullázása
  -> camera.home()               # ismert kiindulás (a rándulás-őrrel)
  -> csipog / felvétel / STT
  -> LÁTÁS-ROUTER: kell-e kép ehhez a kérdéshez?
       igen -> camera/frame.grab_jpeg()  -> vision.CloudVLM.describe()  -> leírás
               (bármelyik lépés bukik    -> a NEGATÍV blokk, ld. 4.5)
       nem  -> nincs [LÁTVÁNY] blokk, a prompt változatlan
  -> RAG (változatlan)
  -> build_prompt(kerdes, hits, latvany=...)
  -> LLM (felhő -> edge) -> nyelvi őr -> tool-ok -> TTS
```

**A képkocka a `home()` UTÁN készül**, tehát a fej ismert helyzetben van, és a leírás arról
szól, amerre a robot NÉZ. (Ha egy `camera` tool a válasz részeként fordítja el a fejet, az
a kör MÁR nem kap új képkockát — a látás a kérdés pillanatához tartozik, nem a válaszhoz.
Ez tudatos egyszerűsítés; a „fordítsd el a fejed, aztán mondd el, mit látsz" két kör.)

### 4.3 Komponensek

| Egység | Mit csinál | Mitől függ |
| :- | :- | :- |
| `camera/frame.py` | `grab_jpeg() -> bytes \| None` — az első `/dev/video*`, ami VALÓDI képkockát ad, 8 bemelegítő kockával, JPEG-re kódolva | `opencv-python-headless` (MÁR függőség) |
| `vision/__init__.py` | `CloudVLM.describe(jpeg) -> str`, `elerheto() -> (bool, indok)` | `vision` beállítások, `health.probe` |
| `vision/router.py` | `kell_e_kep(kerdes) -> bool` — determinisztikus kulcsszó-lista | — |
| `rag/context.py` | `build_prompt(..., latvany=...)` — a `[LÁTVÁNY]` blokk | — |
| `config/settings.py` | `VisionSettings` + `VISION` szekció az env-felülíráshoz | — |
| `orchestrator/` | a fenti bekötése + `transcript.Interakcio.latvany` | mind |

**A képkocka-elkapás nem új kód.** A `scripts/self_check.py` `_elso_kepkocka()`-ja MÁR
megoldotta a nehezét: a Pi 5-ön 20+ `/dev/video*` van, a felük ISP/kodek csomópont, ami
megnyílik, de nem ad képet — **a jelenlét nem bizonyíték, a képkocka az** —, és az első
kockák feketék, amíg az automatika beáll (ezért a 8 bemelegítő kocka). Ez **átköltözik**
`camera/frame.py`-ba, és a `self_check.py` onnan importálja. Nem másolat: egyetlen
implementáció, két hívó.

**Miért a `rag/context.py` építi a `[LÁTVÁNY]` blokkot is**, a névbeli kellemetlenség
ellenére: az a modul ma az EGYETLEN prompt-összeállító, és a két blokk kölcsönhatásban van
(a `KIFEJTOS_MONDAT` hosszpadló csak a forrásos ágon van, mérésből). Két külön
prompt-építő némán elcsúszna egymástól. A névadási adósság rögzítve; ha a modul harmadik
blokkot is kap, akkor költözzön `prompt/`-ba.

### 4.4 A `[LÁTVÁNY]` blokk

```
[LÁTVÁNY]
<a VLM nyers leírása>
[/LÁTVÁNY]

Ezt látod MOST a kamerádon. A magad szavaival mondd el. Amit nem látsz rajta, arról
ne állíts semmit.

Kérdés: <a kérdés>
```

A megfogalmazás a RAG meta-szivárgás tanulságát követi: a régi RAG-instrukció („Az alábbi
forrás alapján válaszolj…") a naplózott válaszok **6,7%-ában** szó szerint visszajött
(„a válasz a forrásban van/nincs"), ezért a forrás-blokk a saját tudásaként van keretezve,
és a forrás megnevezése tiltott.

**⚠️ ITT VISZONT ASZIMMETRIA VAN, és ez a lényeg:** a látás-ágon a visszapapagájozás nem
baj — ha a modell azt mondja, „ezt látom a kamerámon", az IGAZ és kívánatos. Amit tiltunk,
az nem a képre hivatkozás, hanem a **képen nem szereplő állítás**. A tiltás iránya tehát
ellentétes a RAG-éval; a szövegezés végleges alakja a WP0 mérésén dől el.

### 4.5 Hibakezelés — a látás hiánya legyen KIMONDVA, ne néma

Bármelyik lépés bukhat: nincs `/dev/video*`, letakart lencse, halott alagút, VLM-időtúllépés.
**Mindegyik ugyanoda fut, és ez szándékos:**

```
[LÁTVÁNY]
A kamerád most nem ad képet.
[/LÁTVÁNY]
```

**Miért explicit negatív blokk, és nem a blokk kihagyása:** a kihagyás pontosan a mai
állapot, amiben a modell konfabulált. A negatív blokk az EGYETLEN dolog, ami a „nem látok"
választ ténnyé teszi a modell számára. A `[FORRÁS]` üres esetével ez NEM
összetéveszthető: ott a néma kihagyás a helyes (mérve — a hosszpadló forrás nélkül
inváziót szül), mert a „nincs rá adatom" a persona része; itt a „nem látok" egy
ÉRZÉKSZERV állapota, amit csak az orchestrátor tud.

A látás soha nem visz safe módba, és soha nem hosszabbítja a kört határtalanul: a VLM-hívás
saját, RÖVID időkorlátot kap (`vision_timeout_s`, javasolt kiindulás 8 s), és a
`korben_elerhetetlen` cache-t használja, tehát halott alagútnál nem várja ki külön az
STT és az LLM próbája után harmadszor is.

**Health check:** `check_vision_endpoint` — **WARNING**, nem CRITICAL. A felhő
on-demand, és a robot látás nélkül teljesen működőképes; egy CRITICAL itt a demó reggelén
safe módba vinné a robotot egy opcionális képesség miatt.

### 4.6 A látás-router

Determinisztikus kulcsszó-lista, nem osztályozó. **A mért RAG-tanulság áll rá:
alkotás-kérés és PARANCS ne kapjon kontextust.** A „Szabi, gyere ide!" nem indíthat
képfeltöltést — a hosszpadló-mérésben épp egy 3 szavas parancsra kirakott mondat-padló
vitte el a `<tool>` blokkot és szült képesség-hallucinációt („Van egy térképem magyar
nyelven és nagy felbontású képekkel").

Kiindulási lista (a WP0 valódi kérdésein finomítandó): `mit látsz`, `látod`, `ki van
előtted`, `mi van előtted`, `nézz körül`, `milyen színű`, `hányan`, `mi ez`, `kit látsz`.

## 5. Adatvédelem — ez új adatosztály

A kép **konferencia-látogatókról** készül, és kimegy a bérelt felhő-GPU-ra. Ez túlmegy a
`transcript.jsonl` eddigi kockázatán, ami a Pi egyetlen nem publikus, nem forgatható adata.

**Szabály: a képkocka SOHA nem kerül lemezre — sem debug posztúrában.** A
`transcript.jsonl`-be csak a szöveges leírás megy (`latvany` mező). Indok: a
`transcript.jsonl` védelme a *retenció* (14 napos logrotate + a demó előtti wipe), és egy
kiszivárgott arckép ugyanúgy visszavonhatatlan, mint egy elhangzott beszélgetés — csak
rosszabb, mert nem is a Teremtőé. A `--debug` kapcsoló ezt NEM nyithatja ki; ha egy
képkockára diagnózis miatt szükség van, az kézi, egyszeri művelet legyen
(`scripts/self_check.py`), ne a futó robot mellékterméke.

**Az előadás narratívájába:** a kép a saját szerverre megy a saját alagúton, nem egy vendor
API-ra, és nem tárolódik. Ez a szuverenitás-üzenet erősítése, nem gyengítése — de csak
akkor mondható ki, ha tényleg így van.

## 6. Tesztelés

| Egység | Az ellenőrzés tétele |
| :- | :- |
| `camera/frame.py` | hamis `VideoCapture`: 8 bemelegítő kocka; a képet NEM adó eszközt átugorja; egyik eszköz sem ad -> `None` (nem kivétel) |
| `vision/` | hamis `opener` (a `test_voice_stt.py` mintája): a JPEG tényleg felmegy; időtúllépés -> `None` + indok; elérhetetlen host -> `jelold_elerhetetlennek` |
| `vision/router.py` | táblázatos: a látás-kérdések igen, **a parancsok és az alkotás-kérések NEM** (a mért ellenpéldákkal) |
| `rag/context.py` | `[LÁTVÁNY]` van/nincs; a negatív blokk szövege; a `[FORRÁS]`-sal EGYÜTT is jól áll össze |
| kontraktus | a `KNOWN_TOOLS` **változatlan** — a látás nem hoz új toolt (őrteszt, hogy ez később se csússzon el) |
| `orchestrator` | a képkocka a `home()` UTÁN készül; a látás bukása nem visz safe módba |

Minden off-Pi futtatható; a hardver-ág `@requires_pi`.

## 7. Munkacsomagok, sorrendben

| # | Csomag | Kimenet | Becslés |
| :- | :- | :- | :- |
| **WP0** | **Spike** — 15-20 valódi kép (stand, arc, letakart lencse, rossz fény, üres fal) × {angol, magyar} × 2-3 modell-jelölt. Mérendő: leírás-minőség, a **nyelv** döntése, a hármas VRAM-együttélés, a kör-idő növekménye. | modell + nyelv döntés, eldobható kód | fél nap |
| **WP1** | `camera/frame.py` — a `_elso_kepkocka` átköltöztetése, `grab_jpeg()`, a `self_check.py` importálja | PR | fél nap |
| **WP2** | `vision/` kliens + `VisionSettings` + `VISION` env-szekció + `ai_stack` modell-pull + health check | PR | 1 nap |
| **WP3** | router + `[LÁTVÁNY]` + orchestrátor-bekötés + `transcript.latvany` | PR | 1 nap |
| **WP4** | **dataset: a látás ÉS a nem-látás** — „van fejem, de nincs szemem", letakart lencse, „mi van mögötted?" | dataset-kör | 1 nap |
| **WP5** | **v15 fine-tune** a Teremtő teljes listájával | modell | 1 nap (bérlés) |
| **WP6** | red-team a látás-úton + élő spoken eval mindkét modellen | jegyzőkönyv | 1 nap |

**WP4 nem hagyható ki**, és nem a WP0-tól függ: az őszinte ág a demó-kockázat fedezete.
Ha az idő elfogy, **a WP4 marad, a WP0-WP3 esik ki** — nem fordítva.

**A v15 tartalma (a Teremtő listája, 2026-09-08):** a v13 (`lora_r` 16) mérhető rontása ·
a v14 nyelv-regressziója (88% → 44%) · a tool-argumentumok gyengesége (kitalált `action`
értékek, hiányzó irány) · a kimondott szöveg és a tool ELLENTMONDÁSA („Balra fordulok" +
`turn right 90`) · a hosszú-koherencia tétel, ami a 8B-n három körön át nem mozdult.

## 8. Kockázatok

1. **🔴 A határidő.** A szoftver-határidő 2026-09-30, a projekt sajátja **2026-10-15** (egy
   hét szándékos tartalék az okt. 21-i előadás előtt). A VLM a terv UTOLSÓ tétele, és
   **nem költheti el a tartalékot**. Kapu: ha 09-30-ra a WP0-WP3 nincs kész, a kör lezárul
   a WP4-gyel, és Szabinak nincs szeme.
2. **Az ÚJ MODELL a kockázat, nem a beépítés.** A minta kész és mért; amit nem tudunk, az a
   VLM viselkedése (mit mond arra, amit lát; mit mond arra, amit NEM lát).
3. **A v12 kikötése áll.** A v15 csak akkor vált demó-modellt, ha az **élő** evalon
   mérhetően jobb. Egy jobb VLM nem menti meg a rosszabb persona-modellt.
4. **Eval-szivárgás.** A WP0/WP6 kérdései a `transcript.jsonl`-be kerülnek, és onnan a
   dataset felé szivároghatnak. A két meglévő védvonal érvényes: az
   `analyze_chat_log.py` EVAL-ÜTKÖZÉS szakasza és a `dataset/_check_leakage.py`.
5. **Késleltetés.** Becsült +2-3 s a látás-körökre (0,4 s képkocka + ~0,4 s feltöltés a
   139 ms-os alagúton + 1-2 s VLM). Csak a látás-kérdéseket érinti. A WP0 méri.

## 9. Definition of Done

- [ ] „Mit látsz?" a színpadon: Szabi vagy IGAZAT mond arról, ami a kamerán van, vagy
      kimondja, hogy nem lát — **konfabuláció nélkül**, letakart lencsével is.
- [ ] A látás bukása (halott alagút, nincs képkocka) nem visz safe módba és nem némít.
- [ ] Egyetlen képkocka sem kerül lemezre, `--debug` mellett sem.
- [ ] A `KNOWN_TOOLS` változatlan; a tool-kontraktus tesztje zöld.
- [ ] A WP4 dataset-kör akkor is bent van, ha a VLM kimarad.
- [ ] `docs/free-droid.md` §„Nyitva hagyott" lezárva vagy frissítve a valós kimenettel.
