# „Nézz körül" — előbb a kamera, aztán a kép

*2026-09-15 · a Teremtővel egyeztetve (brainstorming, két jóváhagyott rész) · kiegészíti:
`2026-09-09-vlm-design.md`*

## 1. A probléma — mérve

A 2026-09-15-i élő menetben (156 kör, `~/free-droid-logs/transcript-2026-09-15.jsonl`) a
látás-kör sorrendje **kép → LLM → tool** volt. A kamerát mozgató kérés tehát a képkocka
UTÁN hajtódott volna végre, ha egyáltalán:

- **„Nézz körül és pásztázz körbe"** (#44): a kép a mozdulat ELŐTT készült, a `camera scan`
  tool pedig a látás-kapun kiesett. A pásztázásnak semmi értelme nem volt.
- **„Nézz a földre, és mondd el, mit látsz"** (#26), **„Nézz lefelé…"** (#28): a kamera nem
  mozdult, a VLM egy ajtót írt le, a 8B „padlót" és „fapadot" mondott — **hazugság**.

A Teremtő: *„helyes sorrend: kamerát mozgat, több képet készít, feldolgozza a látottakat."*

## 2. Döntések

| # | Döntés | Indok |
| :- | :- | :- |
| 1 | **Három állomás a „nézz körül"-re:** előre (középről) → balra 45° → jobbra 45° (a középhez képest), vízszintesen | A kamera széles látószögű; ~7 s még élő pillanat a színpadon; irányonként elmondható. |
| 2 | **Képenként egy VLM-hívás**, az irány-címkét az orchestrátor adja | Determinisztikus irány; a `qwen3.5:4b` egyképes minősége mért (WP0), a többképesé nem; egy rossz kép nem viszi el a többit. |
| 3 | **Az egyirányú kérés ugyanez, egy állomással:** „nézz fel / le / balra / jobbra, és mondd, mit látsz" | Ugyanaz a kód; a #26/#28 hazugságát is megszünteti. |
| 4 | **Az orchestrátor hajtja végre a router nézési tervét** — nincs új tool, a modell nem vezérel | A tool-kiadás mérten gyenge; a látás-kapu (`{stop}`) érintetlen marad. Elvetve: kétlépcsős 8B-vezérlés (késés + kapu-lyuk), kamera-gesztus visszahívással (a kamera a látáshoz kötődne). |
| 5 | **Új azonosítók angolul** | A Teremtő kérése; a meglévő magyar nevek átnevezése a demó utáni backlog. |

## 3. Komponensek

### 3.1 Router — `vision/router.py`

`vision_plan(question: str) -> tuple[Station, ...] | None`

- `None`: nem kell kép (a mai `False`).
- `Station(label: str | None, pan_deg: float | None, tilt_deg: float | None)` — a `None`
  szög azt jelenti: **maradjon az aktuális póz** (a sima „mit látsz"); a `None` címke
  azt, hogy a sor címke nélkül kerül a blokkba.
- A `kell_e_kep()` megmarad, egysoros burokként: `vision_plan(kerdes) is not None`.

Prioritás, az első illeszkedő nyer:

| Kérés | Terv |
| :- | :- |
| **körbenézés** — „nézz körül", „nézz körbe", „nézz szét", „nézzél körül/szét", „pásztázz körbe" | `Előre (0, 0)`, `Balra (+45, 0)`, `Jobbra (−45, 0)` |
| **irány + látás-jel** — „nézz fel/felfelé/a plafonra/a mennyezetre", „nézz le/lefelé/a földre", „nézz balra", „nézz jobbra", ÉS a kérdésben egy meglévő látás-kifejezés (`látsz`, `lát`, STT-alakok…) | egy állomás: `Fent (0, +30)` / `Lent (0, −30)` / `Balra (+45, 0)` / `Jobbra (−45, 0)` |
| **sima látás-kérdés** (a mai lista) | `Station(None, None, None)` — egy kép az aktuális pózból |

- 🔴 **A „fel" és a „le" STOPSZÓ** a `rag.normalize`-ban: a `tokenize("nézz fel")` és a
  `tokenize("nézz le")` egyaránt `['nezz']`. Az irány-felismerés ezért a stopszó-szűrés
  ELŐTTI, ékezetfosztott szavakon fut (`_fold` + `_TOKEN` a `rag.normalize`-ból — a
  meglévő segédek, nem egy második ékezetfosztó), nem a `tokenize()` kimenetén.
- **A csupasz „Nézz fel!" NEM látás-kérdés** (nincs látás-jel): az továbbra is egy sima
  `camera tilt` parancs a modelltől, nem látás-körben, tehát a kapu nem érinti.
- A hálózati tiltás (`halozat`, `wi`, `ssid`, `wifi…`) és az STT-alakok (`mitlát`, `látze`,
  `látza`, `lats`, `lads`) a `fix/vision-router-stt-wifi` szerint megmaradnak, és MINDEN
  ágra érvényesek.
- A pan előjele: balra pozitív (`PAN_LEFT_SIGN = 1`), a tilt felfelé pozitív
  (`TILT_UP_SIGN = 1`). Mért tartomány: pan +56,4° / −78,9°, tilt ±53,6° — a ±45 és a ±30
  belefér.

### 3.2 Kamera — `camera/__init__.py`

`PanTiltCamera.move_to(pan_deg: float, tilt_deg: float) -> None` — abszolút póz, a meglévő
holtjáték-kompenzált úton (`_beall_holtjatek_nelkul`), mindkét tengelyen. A `pan`/`tilt`
relatív és hozzávetőleges, ezért nem arra épül. A `CameraController` Protocol kiegészül.

### 3.3 Beállítások — `VisionSettings`

| Mező | Alap | Mit hangol |
| :- | :- | :- |
| `look_side_deg` | 45.0 | balra/jobbra kitérés |
| `look_up_deg` | 30.0 | felfelé |
| `look_down_deg` | 30.0 | lefelé |
| `settle_s` | 0.5 | várakozás a pózváltás után, a kép előtt (a szervó beállása + a rázkódás lecsengése) |

Env-ből felülírhatók (`FREEDROID_VISION_*`, a meglévő általános betöltő). Validáció:
mind `> 0`.

### 3.4 Orchestrátor — `_latvany()`

1. `vision_plan(kerdes)`; `None` → `None` (nem látás-kérdés, a prompt nem nő).
2. `self.vlm is None` → `LATVANY_NINCS` (változatlan).
3. **Egyszer** `self.vlm.elerheto()` — halott alagútnál NINCS pózváltás és kép →
   `LATVANY_NINCS`.
4. Állomásonként:
   - ha a `stop_event` (a hurok `trigger.allj`-ja) jelez → a ciklus MEGÁLL, a már kész
     sorok maradnak;
   - ha a szög nem `None` (**`is not None`** — a `0.0` érvényes cél, `bool(0.0)` hamis) →
     `camera.move_to()`; a `settle_s` várakozás CSAK akkor, ha a póz ténylegesen változott
     (a kör eleji `home()` után az `Előre (0, 0)` nem mozdít);
   - `grab_jpeg` → `describe` → `idegen_szoveg_tisztit` → sor.
5. A blokk sora: `címke: leírás`, ha a `label is not None`; különben címke nélkül. Tehát a
   sima „mit látsz" címke nélkül megy (mint ma), az egyirányú viszont címkével
   (`Lent: …`) — a 8B-nek ez a kapaszkodó, hogy MERRE nézett.
6. **Póz a válasz alatt:** egyirányú kérésnél a kamera a pózban marad (természetes
   tekintet); **körbenézés után visszaáll középre** (`move_to(0, 0)`, kép és várakozás
   nélkül) — különben jobbra 45°-ban kitekerve beszélne a közönség helyett. A kör eleji
   `home()` változatlan.

Az `ask()` új, opcionális paramétere: `ask(kerdes, stop_event: threading.Event | None = None)`
— a hurok a `trigger.allj`-t adja át; a szöveges út (`ask_smoke`, tesztek) `None`-nal fut.

## 4. Hibakezelés — a látás sosem viszi el a kört

| Eset | Viselkedés |
| :- | :- |
| Halott alagút / VLM nem érhető el | az 1. próba bukik → nincs mozgás, nincs kép → `LATVANY_NINCS`. A próba a meglévő `probe_timeout_s` (0,5 s) + a kör `korben_elerhetetlen` cache-e — nem a 8 s-os generálási korlát. |
| A `move_to()` dob egy állomáson (I2C-hiba) | a sora: `Jobbra: a fejem nem fordult oda.` — a korábbi állomások leírásai MARADNAK (a hibát állomásonként fogjuk, nem a külső `try`) |
| Egy állomás nem ad képkockát | a sora: `Balra: nem adott képet a kamera.` — a többi állomás MEGY (kamerahiba, nem host) |
| Egy VLM-hívás bukik (időtúllépés, hiba, üres leírás) | a HÁTRALÉVŐ állomások kimaradnak (host-baj valószínű), a meglévő sorok maradnak; ha egy sincs → `LATVANY_NINCS`. Legrosszabb eset egy `timeout_s` (8 s), nem három. |
| `self.camera is None`, de a terv mozgást kér | egy kép előre, és a blokk első sora: `A fejed most nem mozdul, csak előre látsz.` — a 8B ne találjon ki semmit oldalra/felfelé |
| Póz a tartományon kívül | a meglévő szög-vágás + warning |
| Kivétel bárhol a látás-ágon | a meglévő `try` → `LATVANY_NINCS` |

## 5. Határesetek

- **Látás-kapu:** változatlanul `{stop}`. Ha a 8B maga is kiad egy `camera` toolt, az
  továbbra is kiesik — a pózt az orchestrátor már beállította.
- **ÁLLJ gomb körbenézés közben:** a motorokat és a beszédet megállítja, és a
  `stop_event` miatt a kamera-sor a KÖVETKEZŐ állomás előtt megáll (PR #135 review: egy
  beakadt kábel vagy megszorult szervó mellett a természetes reakció az ÁLLJ, és még
  ~7 s mozgatás kárt tehet). A folyamatban lévő egyetlen VLM-hívást nem szakítja félbe.
- **Kritikus akku / hibás watchdog:** a fej mozoghat — a tiltás a lánctalpakra vonatkozik.
- **Adatvédelem:** legfeljebb 3 képkocka megy fel, lemezre egy sem (spec §5 változatlan).
  INFO-n állomásonkénti időzítés, a leírás szövege csak DEBUG-on. A `transcript.latvany`
  a teljes címkézett blokkot tárolja (debug posztúra).
- **Időköltség:** „nézz körül" ≈ (0,8 s kép + ~1 s VLM) + 2 × (0,5 s beállás + ~0,8 s kép + ~1 s VLM) + ~0,3 s vissza középre ≈ 6,7 s (az `Előre` a `home()` után nem vár);
  egyirányú ≈ 2,3 s; sima „mit látsz" változatlan.

## 6. Tesztelés

- **Router:** táblázat — kifejezés → várt állomáslista (körbenézés, a négy irány látás-jellel,
  a csupasz „Nézz fel!" → `None`, sima „mit látsz" → egy `None`-szögű állomás), plusz a wifi-
  és STT-esetek. A 2026-09-15-i 16 élő átirat-eset regressziós tesztként.
- **Kamera:** `move_to()` abszolút célra érkezik, holtjáték-kompenzáltan — a meglévő
  hardver nélküli fixture-rel (`test_camera_home.py` mintája).
- **Orchestrátor:** hamis kamera és hamis `grab_jpeg` EGY közös eseménylistába ír.
  🔴 **A kulcsteszt a mai hibát fogja:** minden képkockát megelőz a hozzá tartozó póz.
  Továbbá: a címkék és a sorrend (egyirányúnál is címke); megállás az első VLM-hibánál;
  egy állomás képkocka nélkül; `move_to` hiba egy állomáson (a korábbi sorok maradnak);
  a `stop_event` megállítja a sort; a `settle_s` csak valódi pózváltásnál; körbenézés után
  vissza középre; a `0.0` szög is mozdít (`is not None`); a kamera nélküli megjegyzés;
  halott alagútnál nincs mozgás.
- **Élő, a Pi-n:** „nézz körül", „nézz fel és mondd, mit látsz", „nézz balra és mondd, mit
  látsz", letakart lencse körbenézéssel, egy kör lekapcsolt felhővel.

## 7. Hatókörön kívül

- A 8B grounding-gyengesége (ellentmond a `[LÁTVÁNY]`-nak) — WP4/v15 dataset.
- A Whisper szótár-prompt javítása a „mit látsz" félrehallásaira — hangfelvétel nélkül nem
  mérhető, külön kör.
- Többképes VLM-hívás, folyamatos videó, mozgás közbeni képkészítés.
- **Párhuzamosítás** (PR #135 review, backlog): amíg a VLM az 1. képet írja le (~1 s), a
  fej már a 2. állomásra fordulhatna és elkészíthetné a képet — ~1,5-2 s nyereség. Most
  szekvenciális, mert egyszerűbb és a hibakezelés (megállás az első VLM-hibánál) így
  egyértelmű; mérés után vehető elő.
