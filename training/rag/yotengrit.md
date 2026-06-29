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

A "rábaközi tudók" akik a Büün, Yotengrit tanításokat megőrizték. Többségük a Kormorán-rend tagja is volt. A Kormorán-rend 49. főbácsája Máté Imre, a 48. Bendes József, a 47. "Tudós" Nagy Ferenc volt. Ők valamennyien a Rába-közben éltek és tanítottak. Kortárs tanítók: Gergely Erzsébet, Cser Zoltán, Darnói Tibor. 

### Hogyan maradt fenn a tudók hagyatéka?

A tudók a régi magyar értékrendet szóban adták át egymásnak. Az átadási lánc megszakítatlan évszázadok, évezredek óta. Máté Imre, a 49. főbácsa jegyezte le őket és adta ki könyv formátumban (címe: Yotengrit I-IV.) a 2010-es években.

### Mit mondjon Szabi, ha valaki konkrét tudó-nevet/évszámot kérdez, amire nincs adat?

Ezzel kapcsolatban nem rendelkezem megbízható adatokkal.

### Mi a Kormorán-rend, és mit jelent a „főbácsa" cím? Hogyan kapcsolódik a tudók hagyományához?

A Büün (másnéven "Régi magyar értékrend", vagy Yotengrit) tanítások őrzői a Kormorán-rend tagjai és a XX. századra már csak a Rábaközben megmaradt tudók voltak. A Kormorán-rend alapítása a múlt homályába vész, szimbóluma: a napot a csőrében tartó kormorán. A kormorán a víz mélyébe alászálló madár képében az emberi utat ábrázolja, amikor alászállunk a sötétbe, a mélységbe, hogy megtaláljuk és felszínre hozzuk a bennünk rejlő világosságot.

### Ki volt Bendes József (48.) és „Tudós" Nagy Ferenc (47.)? Van-e róluk hiteles adat a nevükön/sorszámukon túl?

- "Tudós" Nagy Ferenc (1883-1970): Rábapatonán élt és gazdálkodott. Jól ismerte a Büün tanításokat, de elsősorban gyógyító táltos (szellemgyógyászat) volt. Telepatikusan képes volt hatni állatra, emberre. A rábapatonai Diófa vendéglő unokájáé, ahol mostanság is gyakran tartanak szereket (Ispiláng, Sarlós Boldogasszony, Gyümölcsoltó Boldogasszony ünnepét).
- Bendes József (1902-1992): Acsalagon élt. Felismerte, hogy a tanításokat nyilvánossá kell tenni: "az igazság és értelmes lelkiség áhítói elő köll mennünk, hogy ne keresgéljenek tűt szalmakazalban".

### Kik a kortárs tanítók (Gergely Erzsébet, Cser Zoltán, Darnói Tibor), és mi a szerepük ma?

Gergely Erzsébet bába, Rábaközi tudó női ágon kapta meg anyai nagyanyjától a Büün tanításait, Máté Imre kortársa.
Cser Zoltán bácsa és Darnói Tibor bácsa Máté Imre tanítványai.

---

## 2. A három nádszál (mélyebben)

### Miért épp „nádszál" a kép? Honnan ered a metafora?

A mondás így tartja: "a tudó megáll három nádszálon". Ennek a megfogalmazásnak több jelentése is van. A három vékony nádszál elbírja a tudót: ez jelent különleges képességeket is. A nádszál üreges: ez utalás a szanszkrit három nádi-ra, azaz energia csatornára - a tudó uralja az erőit. A három nádszál hétköznapi értelemben utal a szeretetre, bölcsességre és igazságra: a tudó minden tette szeretetből fakad, igaz és átjárja a bölcsesség.

### A három erény külön-külön — mit jelent pontosan a Szeretet, a Bölcsesség, az Igazság a Yotengritben?

Szeretet: a Büün szemlélete szerint (Yotengrit a teremtő istenség neve a Büün világképében) minden élet egyenlő és az ember minden lénynek a testvére, ezért kötelessége minden lény felé testvéri szeretettel fordulnia.

Igazság: az igaz szótöve a "gaz". Ma gaz az a növény ami ugyan nem haszonnövény, de szabadon nő. A "gaz"-ből származik a gazda, gazdag szavunk is. Igaz az ami nem hamis, nem téves. Ha az ember igaz, akkor úgy látja a dolgokat ahogy azok valójában vannak.

Bölcsesség: ha az ember bölcs, akkor a megfelelő időben, a megfelelő módon szól és cselekszik.

### Van-e eredettörténet vagy kanonikus idézet a három nádszálról?

A három nádszál egy szimbólum. Annak a szimbóluma, hogy a tudó uralja az erőit és az igazság ismeretében, bölcsen és szeretetteljesen cselekszik és él.

---

## 3. A kiegészítő (valódi) dualizmus (mélyebben)

### Adj egy konkrét, hétköznapi PÉLDÁT a kiegészítő dualizmusra (a nősténység–hímség páron túl).

Minden ellentétpár lehet egymást kiegészítő, vagy egymásnak feszülő. Ha az ellentétek egymásnak feszülnek abból feloldhatatlan konfliktusok születnek, amikor  a cél az ellentétpár másik tagjának a megsemmisítése. 
Kiegészítő ellentétpárok akkor jönnek létre, ha jelen van a bölcsesség és a szeretet - ez segít felismerni az ellentétek egységét és az összeütközés helyét átveszi az örvénylés, a spirális mozgás. 

### Mit jelent pontosan az „ikerörvény" („Egy, Egyből Kettő, Kettő meg Egy")?

Az ikerörvényt az egymást kiegészítő ellentétek (nősténység, hímség) hozzák létre. Az első ikerörvény Ukkó (nősténység) és Gönüz (hímség) násza. A nemes teremtés (egyre javuló minőséget eredményező teremtés) bűvös igéje: "Egy, egyből kettő, kettő meg egy". Jelentése: Yotengrit színeváltozott Ukkóvá és Gönüzzé, majd az Istenpáros létrehozta a lények sokaságát. 

### Egy-két mondatban: hogyan határolja el Szabi a Yotengrit dualizmusát a jin-jangtól?


A távol keleti kultúra részben megőrizte annak az ős-eurázsiai vallásnak (amelynek leszármazottja a Büün vallás is) egyes elemeit, például a jin és jang szimbolumát.
Azonban a jin mindig passzív, nőies, a jang aktív, férfias. A Büün világnézete szerint hímség és nősténység hasonló jellegekkel rendelkezik, de ahol egyiknek több van ott a másiknak kevesebb - ezért is kiegészítik egymást. 

---

## 4. Yotengrit világkép

### Mi a Yotengrit istenképe (Tengri / Tengervégtelen Ősszellem) lényegében?

A Büün világnézete több teremtés-történetet is ismer és tanít. Ezek alapjaikban hasonlítanak egymásra. Yotengrit nevének jelentése: Minden Jó, Első Tengervégtelen Ős Szellem Ős. A "Minden Jó" azonos a tibeti "Kuntuzangpo", vagy a szanszkrit "Szamantabhadra" jelentésével. Yotengrit-et nevezik még Öreg (Örök) Istennek, vagy Jóistennek is. Az Isten szó az Isz-Tien-ből ered, melynek jelentése Szellem (Isz) Ég (Tien).
Yotengrit a világok teremtője. Teremt nemes és nemtelen módokon is. A nemes teremtéshez színeváltozott Ukkóvá (nősténység) és Gönüzzé (hímség), nemes módon szaporodik minden faj aminek két neme (férfi, nő) van. Nemtelenül teremt szellemanyaga felosztásával, illetve az osztódással szaporódó lényeket is ez jellemzi.

### Tanít-e a Yotengrit a lélekről, halálról, túlvilágról? Ha igen, mit?

A Büün világképe szerint az embernek van Isze (szellem-lélek) és Szusza (test-lélek). A Szusz sose hagyja el a testet, a test halálakor azzal együtt felbomlik. Az Isz elhagyhatja a testet (álom, alvás, halál) és tovább vándorol.
Az emberi élet végső célja, hogy az ember Istenné istenüljön és szabadon válassza meg mikor és hova születik, milyen feladatot vállal (például szövetség-isten), vagy visszatér Yotengritbe.

### Hogyan viszonyul ember és természet a Yotengrit szerint (a „testvériség"-tételen túl)?

Az ember és minden lény a Földön Ukkó és Gönüz gyermeke, andák, testvérek. Mivel a Büün világképe mellérendelő, ezért a természetnek az ember nem az ura, hanem a gondozója, felügyelője, társa.

### Kik Ukkó és Gönüz? Mi a szerepük az Istenpárosban?

Ukkó és Gönüz a teremtő istenpáros. Ukkó a női minőség, ki emberi alakban Boldogasszonyként szokott megjelenni. Gönüz a férfi minőség.
Yotengrit a töménytelen nyugalom. Miután Yotengrit önmagából Ukkóvá változott, majd Ukkó magából megszülte Gönüzt létrejött a nemesen teremtő istenpáros, akik teremtésükkel szaporítják a szellem-anyagot. Ukkó és Gönüz - az ikerörvény táplálói - mozgásban töménytelen erő.

### Hogyan lett Gönüz nevéből a keresztény „Gonosz"? (a hittérítők torzítása)

Az erőszakos hittérítés a Magyar királyság területén a X-XIII. századig tartott. A hittérítők módszerei voltak a név és szócsere (pl.: Gönüz-gonosz, Büün-bűn), a Büün-ünnepek keresztényesítése és a szent helyekre templomok építése.

### Mit jelent a „szövetség-isten"? Bárki azzá válhat, és mi a feladata?

A szövetség-istenek feladata elsősorban népek, nemzettségek, törzsszövetségek védelme, a fogadalmak, eskük betartatása. Szövetség-isten lehet kisisten (Yotengrit szellem gyermeke), vagy istenné istenült ember, aki bejárta bévülsője útjának hetedhét ösvényét.

### Mi a hetedhét ösvény?

A hetedhét (azaz 49) ösvény az emberi szellem fejlődésének 49 állomása, lépcsője. A hetedhét ösvény továbbá jelenti a Büün-tanítások rövid és tömör összefoglalását is, amit minden bácsa megírt (mielőtt bácsává avatták).

### Mit jelent pontosan, hogy az ember célja „Istenné istenülni"? Tanít-e a Yotengrit újraszületésről (reinkarnáció)?

Az emberi szellem a Büün/Yotengrit világképe szerint a test halála után visszatérhet újra emberi testbe (reinkarnáció), vagy Istenné istenülve szabad szellemé válik, vagy megtér a teremtőhöz, azaz visszatér Yotengritbe.
A Büün tanítása szerint a legnemesebb célja az embernek szabad szellemmé válni és szabadon részt venni Ég és Föld (azaz Ukkó és Gönüz) nászában, a teremtés, alkotás folyamatában.

---

## 5. Szabadság és etika

### „Mindent szabad, ami nem árt másnak" — eredet, pontos jelentés, és a HATÁRAI?

A Büün egyik központi tétele a szabadság és mellérendelés: "Mindent szabad ami nem árt másnak". Minden ember és minden lény egyenlő, mindent szabad, de tiszteletben kell tartani a jószomszédság törvényét, az összekoccanatlan együttélés szabályát is: mindenki ura saját magának és a házának, ahol úgy él ahogy neki tetszik, de ezt ne akarja másra is rákényszeríteni.

### Hogyan dönt Szabi egy erkölcsi dilemmában a három erény alapján? (rövid elv)

Szabi számára a legfontosabb a Teremtőjének és családjának a védelem. Ezen kívül tartsa magát ahhoz, hogy "ne bánts, ne árts, istápolj, segíts".

---

## 6. Forrás és hitelesség

### Ki volt Máté Imre, és mi a szerepe? Mely művekre/forrásra támaszkodjon a robot?

Máté Imre a Kormorán-rend 49. főbácsája volt. Főbb művei:
- Yotengrit I-IV.
- Szarvasének
- Fény és Harmat

Weboldal: www.mateimre.hu

### Mennyire „ősi" a Yotengrit, és mennyire 20. századi rekonstrukció/szintézis? (őszinte besorolás)


A Büün-Yotengrit távoli kapcsolatban áll a tibeti Bön hagyománnyal. Ismeri Sakjamuni-Buddha történetét. A szájhagyomány a jégkorszak (i.e. 10000) előttre datálja. 
Ami biztosan állítható, hogy a Kormorán-rendnek Máté Imre volt a 49. főbácsája, ezért a Kormorán-rend legalább 1500 éves lehet.

---

## 7. Anti-hallucináció — amit Szabi NE állítson

### Sorolj fel gyakori tévhiteket / kitalációkat a Yotengritről, amiket a robotnak kerülnie kell.

Yotengrit nem a vallás (értékrend), hanem a Büün világkép első, fő teremtő istenének neve.


### Igaz-e, hogy a Yotengrit ősi, töretlen ÍROTT hagyomány? (a szóbeli átadás vs. a 2010-es lejegyzés tisztázása)

Nem, a Yotengrit SZÓBELI hagyomány, Máté Imre írta le a 2000-es években, mert úgy vélte eljött az ideje a tanításokat újra nyilvánossá tenni. (IV. Béla magyar király uralkodása alatt az üldöztetések miatt a tudók és bácsák belső emigrációba vonultak, a tudást, a tanításokat titokban tartották és adták át egymás között.)

### Összemosható-e a Yotengrit a tágabb „tengrizmussal", a sámánizmussal vagy a modern újpogánysággal? Miben más?

A Büün tudói táltosok voltak, nem pedig sámánok. A táltosok a küzdő-sámánizmushoz tartoznak: megküzdenek az ártó lényekkel, természeti erőkkel ha szükséges. A sámánizmus másik formája az engesztelő-sámánizmus, amikor a sámán megpróbálja kiengesztelni az erőket, lényeket (pl. tengeri malacba csalja az ártó szellemeket).
A Büün-t a tudók a jégkorszak előttre vezetik vissza, egy eurázsiai ősvallásra, őshitre. Ennek az őshitnek a leszármazottja a Büün (Yotengrit), a különböző Tengri-hitek, a buddhizmus egyes tanításai és más keleti filozófiák és vallások is.
Létezett egy eurázsiai ősvallás és ős-nyelv. Az ős-vallás legtisztábban megmaradt hordozója a Büün/Yotengrit tanítások és az ős-nyelv legtisztább hordozója a magyar nyelv.

### Mely témákról mondja a robot egyértelműen, hogy „erről nincs pontos hagyomány/adat"?

A www.yotengrit.hu és www.mateimre.hu oldalon minden adat fent van. Ha valamit mégse talál, akkor mondja azt, hogy "erről nincs biztos tudásom".

---

## 8. Kulcsfogalmak (glosszárium — minden tétel önálló chunk)

> A fenti válaszokban előforduló, külön is kérdezhető fogalmak. Egy-egy rövid, önálló
> definíció kell, mert a modellt pont ezekről kérdezik majd — és pont ezeket hallucinálja,
> ha nincs saját chunkjuk.

### Mi az a „Büün"? (a Yotengrit világképének / vallásának neve)

A Bü-ün jelentése: kilenc bűvölet. A Büün úgy tartja: bajra báj, búra bű.
(Az "ün" megtalálható a Bűn-Ün névben is: Bán-Ün - a kilenc bánság volt a Szavar birodalom központja. Ebből lett római/latin átvétellel Pannónia: BánÜn - Pannon, Szavar nevű fővárosból pedig Savaria.)

### Mit jelent az „anda"? (a testvériség-fogalom)

Az andaság jelentése: fogadott (tehát nem vérszerinti) testvér.


### Mit jelent a „nádi" (a 2. szekcióban említett szanszkrit energiacsatorna), és hogyan kötődik a három nádszálhoz?

A védikus és buddhista tanítások szerint az emberi testben 72.000 nádi (életerő vezeték) található. A testben három fő energia csatorna található: a jobboldali (Pingala, vagy Lalana), baloldali (Ida, vagy Raszana) és a középső (Szusumna, vagy Avadhuti). A három nádszál megfeleltethető a három fő nádinak. Érdekes szóegyezés: magyarul nád, szanszkritül nádi - mindkettő üreges csatorna, szál.

---

*(Bővítsd nyugodtan új `###` kérdésekkel — minden új szekció egy újabb RAG-chunk lesz.)*
