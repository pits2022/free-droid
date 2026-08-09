# Orchestrátor-routing: a „reflex-réteg" terve

*2026-08-09 · a Fázis 4 bekötéséhez, hardver előtt*

## Miért, egy mondatban

A begyakorolt parancs ne múljon azon, hogy a nyelvi modell épp melyik szót hallja meg.

## A vezérelv a Teremtőtől — és ez nem hasonlat

> Ha tüskébe lépek, felkapom a lábam anélkül, hogy tudatosodna. A tánctanulás is arról
> szól, hogy az izommemóriába rakjuk a mozgást — automatizáljuk.

Ez pontosan a rétegzés, ami kell:

| biológia | nálunk | állapot |
| :--- | :--- | :--- |
| gerincvelői reflex (tüske) | `safety.UltrasonicWatchdog` → `motion.stop()` | tervezve, LLM-től független |
| **izommemória (tánc)** | **szándék-router — EZ A DOKUMENTUM** | hiányzik |
| tudatos gondolkodás | LLM (felhő 8B, edge fallback) | tervezve |

És a szabályt is a biológia adja: **az izommemóriába az kerül, amit begyakoroltunk.**
Az új vagy szokatlan mozdulat továbbra is tudatos. Ezért a router **szűk és
nagy magabiztosságú** — nem „a parser mindent elkap", hanem „a begyakorolt készlet
nem kér engedélyt a gondolkodástól".

## A MAI útvonal (a kódból, nem emlékezetből)

```
wake ("Szabi") → felvétel → Whisper (STT) → LLM.generate → válasz-SZÖVEG
                                                             ├→ TTS
                                                             └→ parse_tools(válasz) → dispatch
```

**A `parse_tools()` a modell UTÁN van.** A `<tool>NAME v1 v2</tool>` *grammatikát*
olvassa, azaz a modell kimenetét — magyar mondatot nem ért. „Fordulj balra 90 fokot"
bemenetre nem csinál semmit. A router tehát **új komponens**, nem a parser áthelyezése.

Külön szálon, ettől függetlenül: `Watchdog → motion.stop()`, sosem kérdezi az LLM-et.

## A TERVEZETT útvonal

```
Whisper-szöveg
   │
   ├─[1]─► SZÁNDÉK-ROUTER ──(találat)──► tool-hívás + fix kísérőmondat ──► dispatch + TTS
   │                                                                      (azonnal)
   └─[2]─► nincs találat ──► RAG-döntés ──► LLM ──► TTS + parse_tools → dispatch
```

Felhős és edge módban **ugyanaz** — ahogy a lábfelkapás sem attól függ, elérhető-e a felhő.

## 1. A begyakorolt készlet (a Teremtő döntése)

**Routerhez:** `move`, `turn`, `stop`, `camera`, `scan_wifi` — determinisztikusak és mérhetők.

**LLM-nél marad:** `set_mode`, `set_speed`, `set_oracle`, `request_navigation_help` — ezek
szándéka tényleg értelmezést kíván (a `request_navigation_help` szabad szövegű célt vesz át).

## 2. Találat esetén azonnal szólal meg (a Teremtő döntése)

Fix kísérőmondat tool-onként („Balra fordulok, Teremtőm."), egyszerre a mozgással.
Az elvetett alternatíva — mozgás azonnal, mondat utólag az LLM-től — élethűbb lenne
(előbb a mozdulat, aztán a tudatosulás), de a demón késleltetett beszédet jelentene.

## 3. ⚠️ A MÉRT gyengeség, amit a terv középpontba tesz

A relé-prototípus szabályai a 25 kérdéses benchmarken **5/5**-öt értek el `tool_calling`-on.
**Beszélt bemeneten viszont elhasalnak** (2026-08-09, ugyanazok a szabályok):

| bemenet | eredmény |
| :--- | :--- |
| `szabi gyere ide` | ✅ tool |
| `fordulj balra 90 fokot` | ✅ tool |
| `fordulj balra kilencven fokot` | ❌ **kimondott szám** |
| `hát ööö fordulj már jobbra hatvan fokot` | ❌ kimondott szám + töltelék |
| `menj előre két métert` | ❌ a `menj` ige nincs is a szabályokban |
| `menj előre 2 métert` | ❌ ugyanaz |
| `pásztázd a wifit` | ❌ a `pásztáz` ige hiányzik |
| **`álljá meg`** | ❌ **a STOP bukott el — beszélt alak** |
| `állj meg` / `szabi állj` | ✅ tool |

Ez **nem a relé cáfolata**, hanem a saját mérésem torzításának a mértéke: a szabályokat a
*written* benchmark ismeretében írtam, és a benchmark kérdései írott alakúak. A színpadon
a Teremtő **beszélni** fog.

**Következmény a tervre:** a router elfogadási mércéje **nem** a persona-benchmark, hanem a
beszélt stílusú tool-mérés (`tool_reliability.py` spoken-variánsa, 2026-08-07). A
2026-08-07-i mérés szerint a *modellnek* a beszélt stílus alig számít (8B 97% → 90%) —
egy **regexnek** viszont nagyon, ahogy fent látszik.

## 4. Aszimmetrikus szigor — ez a legfontosabb biztonsági döntés

A hibák nem egyformán veszélyesek:

- **`stop` — a téves NEGATÍV a veszélyes.** Ha nem áll meg, kár keletkezik. Ezért a `stop`
  illesztése legyen **tág**: `állj`, `állj meg`, `álljá`, `megállj`, `stop`, `elég`, `várj`,
  és a puszta „Szabi!" is, ha mozgás közben jön. A téves megállás ára nulla.
- **`move` / `turn` — a téves POZITÍV a veszélyes.** Egy félrehallott mondatra elinduló robot
  a közönség között áll. Ezért ezek illesztése **szigorú**: kelljen hozzá explicit
  mozgás-ige ÉS (irány VAGY távolság). Bizonytalanság esetén **essen át az LLM-hez**, ne
  találgasson a router.
- `camera`, `scan_wifi` — olvasó műveletek, se mozgás, se hálózati beavatkozás. Közepes
  szigor elég. (A `scan_wifi` továbbra is **kizárólag felsorolás**, csatlakozás soha —
  ez a szuverenitás-invariáns, nem routing-kérdés.)

**A watchdog fölötte áll mindennek.** A router sosem kerülheti meg, és `safe_mode`-ban a
mozgás-tool-ok a routerből is tiltottak — a router nem lehet kiskapu.

## 5. Amit a routernek tudnia kell a beszédről

1. **Kimondott számok.** `kettő/két`, `kilencven`, `harminc`, `száznyolcvan` → szám. Enélkül
   a leggyakoribb parancsforma bukik. (A 8B ezt 3/3-ban megoldotta — a router ne legyen
   rosszabb, mint amit lecserél.)
2. **Ige-lefedettség.** Legalább: `gyere`, `jöjj`, `menj`, `indulj`, `fordulj`, `pásztázd`,
   `nézz`, `állj`, `megállj` — és beszélt/nyelvjárási alakjaik.
3. **Töltelékszó és írásjel-hiány** ne számítson (a prototípus ezt már bírja).
4. **Ha nincs szám**, de van irány (`fordulj balra`), az alapértelmezett szög a
   `config`-ból jöjjön — ne a routerbe égetve.

## 6. RAG-routing: a szándék dönt, nem a kérdés alakja

Mérve, nem feltételezve:

- **Tudás-kérdés → kap `[FORRÁS]`-t.** (tech-próba 18/20, Yotengrit 4/4.)
- **Parancs → SOHA.** A `Mit látsz a hálózaton?` kérdés alakú *parancs*.
- **Alkotás-kérés → SOHA.** Mérve: groundolva 4/4 kimenet elvesztette a vers-formát,
  groundolatlanul 4/4 megtartotta; az egyik válasz a chunkból idézett etimológiát haiku
  helyett. (Ezért maradt ki a `mondj`/`írj` a kérés-ige stopwordökből.)

A router találata egyben azt is jelenti, hogy **nem megyünk RAG-hoz** — a parancs nem
tudás-kérdés.

## 7. Hogyan tudjuk meg, hogy működik

| mit | mivel | küszöb |
| :--- | :--- | :--- |
| begyakorolt parancsok, **beszélt** stílusban | `tool_reliability.py` spoken-variáns | a routernek ≥ a 8B mai értéke |
| **téves pozitív** (nem-parancs elindítja-e) | a 673 valódi chat-kérdés a naplókból | **0** mozgás-tool |
| `stop` recall | célzott lista beszélt alakokkal | **100%**, ez nem alkuképes |
| nem romlott-e a többi | persona-benchmark, vakon | ne essen a v12 szintje alá |

A **téves pozitív** mérése a fontosabb, és ingyen van: a `szabi-logs` 673 egyedi kérdése
mind olyan, amire a robotnak **nem** kellett volna elindulnia.

## 8. Amit szándékosan NEM csinálunk

- **Nem tanulunk ML-lel szándékot.** Egy második modell ugyanazt a megbízhatatlanságot hozná
  vissza, amit a router megszüntet — és nem lenne olvasható, hogy miért indult el.
- **Nem visszük a routerbe a teljes tool-készletet.** A `request_navigation_help` szabad
  szövegű célja értelmezés, nem illesztés.
- **Nem a router dönt a biztonságról.** Az a watchdogé, külön szálon, változatlanul.

## Nyitott kérdés a Pi 5-ös élő tesztig

A relé (modell nélküli fallback) és a router **ugyanaz a mechanizmus**, más helyen: a relé
edge módban helyettesíti az LLM-et, a router mindkét módban elé kerül. Ha a Pi-teszt a relét
igazolja, a kettő **egy** komponens legyen, két belépési ponttal — ne két, külön drift-elő
szabálykészlet.
