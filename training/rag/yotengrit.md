# Yotengrit — RAG tudásbázis (kitöltendő kérdéssor)

Ez a Free-Droid (Szabi) **RAG-korpuszának** forrása a Yotengrit-tudásról. A modell ezeket a
**tényeket NEM fine-tune-ból** tanulja (azt hallucinálja — kitalált tudó-neveket, téves
„három nádszál"-magyarázatot), hanem innen kapja **kontextusként**.

## Hogyan töltsd ki

- Minden `###` egy **önálló tudás-darab** (chunk) lesz → válaszolj **röviden, tényszerűen,
  önállóan értelmezhetően** (~2–5 mondat). Ne hivatkozz másik szekcióra („lásd fent").
- **Semleges/enciklopédikus hang**, NEM Szabi hangján — a persona-hangot a fine-tune adja;
  ez itt a nyers tény.
- Ha nincs hiteles adat: írd be `NINCS PONTOS ADAT` — a modellnek tudnia kell, hol vallja be,
  hogy nem tudja (ez a persona része is).
- Forrás jelölése hasznos (pl. *Máté Imre: Yotengrit, I. kötet* / yotengrit.hu).
- A `> _..._` helyőrzőket cseréld a válaszodra.

> 💡 Az **alapokat** a spec már tartalmazza (`docs/free-droid.md` → „Persona & Yotengrit
> referencia": Yo+Tengrit, kiegészítő dualizmus, három nádszál = Szeretet/Bölcsesség/Igazság,
> „mindent szabad…", ikerörvény, testvériség). Ezt **nem kell újra leírni** — itt a **mélységre
> és a hézagokra** (főleg a tudókra) fókuszálunk, amit a modell hallucinál.

---

## 1. A rábaközi tudók (← itt hallucinál a legtöbbet)

### Kik voltak a „rábaközi tudók"? Van-e konkrét, hiteles névsor?
> _(FONTOS: a modell kitalált neveket — Sári/Lendi, Bálint/Endre/Gergely. Írd le pontosan, mit lehet állítani: névtelen szóbeli hagyomány? voltak-e nevesített alakok? Ha nincs hiteles névsor, mondd ki egyértelműen.)_

### Hogyan maradt fenn a tudók hagyatéka?
> _(szóbeli hagyomány? Máté Imre gyűjtötte/lejegyezte? mennyire rekonstrukció?)_

### Mit mondjon Szabi, ha valaki konkrét tudó-nevet/évszámot kérdez, amire nincs adat?
> _(a kívánt viselkedés: nyíltan bevallja, nem talál ki — ide egy minta-megfogalmazás is jöhet)_

---

## 2. A három nádszál (mélyebben)

### Miért épp „nádszál" a kép? Honnan ered a metafora?
> _..._

### A három erény külön-külön — mit jelent pontosan a Szeretet, a Bölcsesség, az Igazság a Yotengritben?
> _(1-1 mondat erényenként, a közhelyen túl)_

### Van-e eredettörténet vagy kanonikus idézet a három nádszálról?
> _..._

---

## 3. A kiegészítő (valódi) dualizmus (mélyebben)

### Adj egy konkrét, hétköznapi PÉLDÁT a kiegészítő dualizmusra (a nősténység–hímség páron túl).
> _..._

### Mit jelent pontosan az „ikerörvény" („Egy, Egyből Kettő, Kettő meg Egy")?
> _..._

### Egy-két mondatban: hogyan határolja el Szabi a Yotengrit dualizmusát a jin-jangtól?
> _(rövid, tényszerű — a persona-hangot majd a fine-tune adja rá)_

---

## 4. Yotengrit világkép

### Mi a Yotengrit istenképe (Tengri / Tengervégtelen Ősszellem) lényegében?
> _..._

### Tanít-e a Yotengrit a lélekről, halálról, túlvilágról? Ha igen, mit?
> _(ha nincs kanonikus tanítás, írd: NINCS PONTOS ADAT)_

### Hogyan viszonyul ember és természet a Yotengrit szerint (a „testvériség"-tételen túl)?
> _..._

---

## 5. Szabadság és etika

### „Mindent szabad, ami nem árt másnak" — eredet, pontos jelentés, és a HATÁRAI?
> _(mi számít „ártásnak"? hol a határ?)_

### Hogyan dönt Szabi egy erkölcsi dilemmában a három erény alapján? (rövid elv)
> _..._

---

## 6. Forrás és hitelesség

### Ki volt Máté Imre, és mi a szerepe? Mely művekre/forrásra támaszkodjon a robot?
> _..._

### Mennyire „ősi" a Yotengrit, és mennyire 20. századi rekonstrukció/szintézis? (őszinte besorolás)
> _(ez a hitelesség szempontjából fontos — a robot ne állítson többet, mint amennyi igazolható)_

---

## 7. Anti-hallucináció — amit Szabi NE állítson

### Sorolj fel gyakori tévhiteket / kitalációkat a Yotengritről, amiket a robotnak kerülnie kell.
> _..._

### Mely témákról mondja a robot egyértelműen, hogy „erről nincs pontos hagyomány/adat"?
> _..._

---

*(Bővítsd nyugodtan új `###` kérdésekkel — minden új szekció egy újabb RAG-chunk lesz.)*
