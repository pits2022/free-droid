# Szabi műszaki adatlap — RAG tudásbázis

Ez a Free-Droid (Szabi) **RAG-korpuszának** második forrása: a saját hardveréről, szoftver-
stackjéről és architektúrájáról szóló **tények**. A Hacktivity-közönség ilyet fog kérdezni
("milyen vason futsz", "mekkora a modell", "mi hajtja a lánctalpat"), és ezek pont az az
adatfajta, amit a fine-tune **nem** taníthat: változnak (szervertípus, modellverzió,
kvantálás), és a súlyokba égetve minden spec-módosítás újratanítás lenne.

Formátum és hang ugyanaz, mint a `yotengrit.md`-ben: minden `###` egy önálló chunk,
**semleges, tényszerű hang** (a persona-hangot a fine-tune adja rá), önmagában
értelmezhető, ~2–5 mondat, nincs kereszthivatkozás.

**Forrás: `docs/free-droid.md` (v2.0 spec) — ez az egyetlen hiteles forrás. Ha a spec
változik, EZT a fájlt kell frissíteni, majd `python -m freedroid.rag.corpus`.**

## 1. Architektúra

### Milyen architektúrára épülsz? Hogyan működik a felhő-edge felépítésed?

Hibrid cloud-edge architektúra, aszimmetrikus felállásban. A felhőben egy nagyobb, az
eszközön egy kisebb nyelvi modell fut, és egy Python orkesztrátor dönti el, melyiket
használja. A sorrend: felhő (ha a WireGuard-alagút él) → edge (offline) → "safe mode"
(előre megírt válaszok, a mozgás letiltva). A felhő on-demand indul, nem folyamatosan fut.

### Miért futtatsz két különböző méretű modellt a felhőben és magadon?

Mert a két hely teljesítménye különbözik. A nagyobb modell választékosabban fogalmaz, de
valós időben nem futtatható a Raspberry Pi-n. A kisebb modell gyorsabb és teljesen offline
működik, cserébe kevésbé ékesszóló. Ez tudatos döntés: az edge egy szuverén, de szerényebb
tartalék, nem a felhő másolata.

### Mi történik veled, ha megszakad a kapcsolat a felhővel? Mi a tartalék működésed?

Nem állok meg. Ha a felhő elérhető, a nagy modell felel a felhőben; ha az alagút megszakad,
a saját, helyi tudásomra váltok — rövidebben és óvatosabban válaszolok, de válaszolok. Ha a
helyi működés is elakad, biztonságos módba lépek: csak előre elkészített válaszokat adok, és
a mozgást letiltom. Az akadályérzékelő reflexem mindhárom állapotban működik, mert az nem a
nyelvi modelltől függ, hanem külön szálon fut.

### Mi a Szuszom és mi az Iszem? Melyik részed a test és melyik a szellem?

A projekt saját elnevezései a két "agyra". A Szuszom a testben lévő kis, gyors processzor,
ami mindig elérhető. Az Iszem a felhőben futó nagyobb tudás és személyiség. A megnevezés
azért fontos, mert a kis modell a megnevezett szakszót meg tudja tanulni, a költői képet nem.

### Miért nem használsz ROS 2-t? Milyen vezérlő szoftver és program fut rajtad?

A mozgásvezérlés sima Python virtuális környezetben fut, `lgpio`-val, `rclpy` nélkül. A ROS 2
későbbi ütemterv, a Hacktivity-hatókörön kívül. A vezérlés így háromrétegű: az LLM szándékot
fogalmaz, a Python vezérlőréteg GPIO/PWM-re fordítja, a biztonsági figyelő pedig külön
szálon, a modelltől függetlenül állít meg.

## 2. Nyelvi modellek

### Milyen nyelvi modellt használsz a felhőben? Milyen LLM, AI hajt téged?

Llama 3.1 8B, finomhangolt változatban, Q4_K_M kvantálással, Ollamán keresztül, kizárólag
inferenciára. A felhő soha nem tanít. CPU-n fut, ami lassú: 8B Q4 még erős x86 laptopon is
csak nagyjából 4-5 token/másodperc. A demón ez vállalható, mert a válaszok rövidek.

### Milyen modell fut magadon, offline? Mekkora, hány paraméteres a helyi modelled?

Llama 3.2 3B, finomhangolva, Q4_K_M kvantálással, körülbelül 2–2.5 GB RAM-ot használva.
Teljesen offline működik, ez az internet nélküli tartalék. A Raspberry Pi 5-ön nagyjából
2-5 token/másodperc a sebessége.

### Hogyan tanítottak be téged? Ki és hogyan készítette a finomhangolásodat?

Google Colab ingyenes T4 GPU-ján, Unsloth QLoRA módszerrel. Sem a felhőszerver, sem a robot
nem tanít — azok csak futtatnak. A tanítás a persona-t és az értékrendet tanítja, nem
tényeket; a tények RAG-ból jönnek. Az eredmény GGUF exportként kerül Ollama Modelfile-ba.

### Miért nyílt forrású modellt használsz?

Mert a szuverenitás lényege, hogy a gazda a `root`, nem egy gyártói felhő. Egy nyílt súlyú
modell letölthető, finomhangolható és helyben futtatható, hálózat nélkül is. A zárt API-s
modellnél a szolgáltató bármikor változtathat a viselkedésen vagy elzárhatja a hozzáférést.

## 3. Hardver

### Milyen hardveren futsz? Mennyi memóriád van, milyen processzor és számítógép van benned?

Raspberry Pi 5, 8 GB memóriával (RAM), aktív hűtéssel. Az operációs rendszer Raspberry Pi OS 64-bit
Lite, Debian Bookworm alapon. Ugyanezen a gépen fut a beszédfelismerés, a kis nyelvi modell
és a beszédszintézis is — együtt nagyjából 5.5 GB a 8 GB-ból, ezért megy a nehéz inferencia
elsősorban a felhőbe, ha van hálózat.

### Hogyan mozogsz? Mi hajtja a lánctalpad, milyen motor és meghajtó van benned?

Két egyenáramú motor, lánctalpanként egy, kék eloxált alumínium vázban. A motorvezérlő egy
Cytron HAT-MDD10, ami közvetlenül a Raspberry Pi 5 GPIO-fejlécére csatlakozik. A motorok a
11.1 voltos akkumulátorról kapnak közvetlen tápot, 25 amperes olvadóbiztosítékon át.

### Milyen akkumulátorod van? Mi a tápellátásod, mennyi ideig bírod árammal?

CNHL LiPo 3S: 11.1 volt, 5200 mAh, 100C terhelhetőség, kemény házban. A tápot egy XT60
elosztópanel osztja szét, vonalanként külön biztosítékkal. A Raspberry Pi egy XL4016
feszültségcsökkentőn át kap 5.1 voltot, a szervók egy LM2596-on át 5 voltot.

### Milyen szenzoraid, érzékelőid vannak? Hogyan érzékeled az akadályt magad előtt?

HC-SR04P ultrahangos szenzorokkal, három darab használatban: elöl, illetve bal és jobb
elöl 45 fokban. A "P" változat 3–5.5 volton működik, ezért az Echo láb feszültségosztó
nélkül köthető a Raspberry Pi GPIO-jára. A szenzorokat külön szál olvassa, és küszöb alatti
távolságnál azonnal megállítja a robotot, a nyelvi modellt teljesen megkerülve.

### Van kamerád? Hogyan mozog, mit lát és merre néz a kamerád?

Két szervómotor mozgatja, egy PCA9685 PWM-vezérlőn keresztül: az egyik a vízszintes
forgatás, a másik a függőleges billentés. A kamera egy USB-s 1080p webkamera. A világítást
egy WS2812 RGB NeoPixel gyűrű adja, SPI módban vezérelve, hogy ne ütközzön a hang- és
motorvezérlés időzítésével.

## 4. Hang és hálózat

### Hogyan hallasz engem? Milyen mikrofonod van, hogyan érted meg a beszédet?

A folyamat teljesen offline fut a Raspberry Pi-n. Ébresztőszó: "Szabi", openWakeWord-del,
saját betanított modellel. A beszédfelismerés Whisper.cpp-vel történik, magyar nyelven. A
hangbemenet USB-mikrofonról jön.

### Milyen hangon beszélsz? Milyen nyelven szólalsz meg?

Piper beszédszintetizátorral, a `hu_HU-anonymous-medium` hanggal, offline. A hangmagasság és
a sebesség fiatalosabbra van hangolva. A magyar nyelv nem korlátozás, hanem a szuverenitási
üzenet része.

### Hogyan kapcsolódsz a felhőhöz? Milyen hálózaton éred el a nagy modellt?

WireGuard VPN-alagúton, a felhőszerver a 10.0.0.1, a robot a 10.0.0.2 címen. Ha az alagút
megszakad, a robot automatikusan a saját, helyi modelljére vált. A felhőt Terraform hozza
létre és bármikor eldobható; a robotot csak Ansible kezeli, terraform destroy nem éri el.

### Milyen szerver fut a felhőben? Hol, milyen gépen fut a nagy modelled?

Hetzner Cloud CAX31, ARM64, kizárólag CPU — GPU nincs. Nagyobb igényre CAX41-re cserélhető,
ez egy soros változtatás a Terraform változóban. A spec eredetileg GEX44-et említett, de az
a dedikált GPU-vonal, ami a Cloud API-n nem elérhető, ezért esett ki.

### Csatlakozol wifire? Rálépsz egy wifi hálózatra, látod a wifi hálózatokat?

Nem. A wifi-funkció csak felsorolás: kilistázza a látható hálózatokat a nevükkel és a
biztonsági szintjükkel, csatlakozni nem tud és jelszót nem kezel. A hálózat beállítása
mindig kézzel, megbízható csatornán történik. Ez szándékos biztonsági korlát, nem hiányosság.
