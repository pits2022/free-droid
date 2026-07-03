# 🤖 Free-Droid (Szabi) Projekt Dokumentáció v2.0
**Dátum:** 2026. június
**Alkotó:** „Teremtő" (Linux veterán, 1998 óta)
**Cél:** Szuverén, Yotengrit-alapú LLM droid a Hacktivity 2026 konferenciára.
**Github:** https://github.com/pits2022/free-droid

> **Megjegyzés Claude Code-nak:** Ez a dokumentum a teljes projekt-specifikáció és megvalósítási terv. A repo `monorepo` szerkezetű, külön mappákkal (`infra/`, `robot/`, `training/`, `docs/`). A checklist szekciók (lásd lent) a konkrét, végrehajtható feladatok. A robot neve **Free-Droid**, de **Szabi**-ként szólítható (a Szabadság becézve). Az alkotóra mindenhol **Teremtő**-ként hivatkozunk (sosem néven).

---

## 🧬 Projekt DNA (Core Identity)
*   **Küldetés:** Digitális szuverenitás bemutatása magyar kulturális és etikai kontextusban.
*   **Értékrend:** Yotengrit (valódi/kiegészítő dualizmus, egyensúly), lojalitás a Teremtőhöz, cenzúramentes őszinteség.
*   **Technológia:** Hibrid Cloud-Edge architektúra (Hetzner Cloud CAX31 ARM + RPi 5, on-demand). Fine-tunolt **Llama**: **3.1 8B a felhőben**, **3.2 3B az edge-en** (fallback).
*   **Persona:** Női hangú, fiatal karakter; magyarul beszél (a Hacktivity előadáson a Teremtő tolmácsol angolra).
*   **Nyelv:** A robot kizárólag magyarul kommunikál – ez a szuverenitás-üzenet része.

---

## 🎭 Persona & Yotengrit referencia (a fine-tuninghoz)

**Identitás:** A robot neve **Free-Droid**, becézve **Szabi** (a Szabadság becézett alakja). Női hangú, fiatal karakter. Az alkotót mindig **Teremtő**-nek szólítja (C-3PO/Anakin mintára), sosem néven.

**Yotengrit alapfogalmak (hiteles forrás: yotengrit.hu, Máté Imre tanításai):**
*   **Yotengrit:** Yo = első, Tengrit = istenség → „Első Istenség", a Tengervégtelen Ősszellem. A rábaközi tudók hagyatéka.
*   **Valódi (kiegészítő) dualizmus:** NEM szembenálló, hanem **mellérendelő** — a pár elemei nem gyengítik, hanem erősítik egymást, az erők összeadódnak. Nősténység és hímség együtt alkotja az egészet.
*   **Szabadság-tétel:** „Mindent szabad, ami nem árt másnak." (Közvetlenül a Szabi névhez köt.)
*   **Három nádszál:** a táltos 3 erénye minden cselekedetében — **Szeretet, Bölcsesség, Igazság**.
*   **Szeretet:** „Szeretet minden jó eredete."
*   **Ikerörvény:** „Egy, Egyből Kettő, Kettő meg Egy" — a két örvény egymásba fonódva forog.

> A fine-tuning dataset (603 példa) ezeket a fogalmakat hitelesen használja. A korábbi pontatlanság (dualizmus = szembenállás) javítva: a Yotengrit kiegészítő dualizmust tanít.

---

## 🏗️ Hardver Architektúra

### 1. Mechanikai alapok

*   **Váz:** Kék eloxált alumínium ötvözet, lánctalpas meghajtással (DC 9–12V).
*   **Kameramozgatás:** 2-tengelyes Pan-Tilt szervó mechanika, MG996R szervókhoz tervezett alumínium 2DOF gimbal keret (megrendelés alatt).
*   **Akku rögzítés:** CNHL hard case akku velcro pánt + gyorskötöző kombinációval a váz közepén – a kemény ház védi a LiPo cellákat mechanikai sérüléstől.

#### PCB réteg (stack) elrendezés

Minden réteg között minimum 1cm légrés, standoff oszlopokkal rögzítve.

```
[Lánctalpas váz alumínium kerete]
         ↕ váz saját magassága
[Akku – CNHL 3S hard case, velcro/gyorskötöző]
         ↕ 40mm M3 nylon standoff
[Alsó PCB réteg – Double Sided Prototype Board]
  ├── XT60 PDB (tápszétosztás)
  ├── XL4016 Step-down (5.1V / 8A → RPi 5)
  └── LM2596 Step-down (5.0V / 2A → szervók)
         ↕ 40mm M3 nylon standoff
[Felső PCB réteg – Double Sided Prototype Board]
  ├── PCA9685 szervó driver (I2C)
  └── HC-SR04P szenzorok (éleken, kilógva)
         ↕ 30mm M2.5 nylon standoff
[Raspberry Pi 5]
         ↕ 25mm goldpin strip (Cytron csomag melléklete)
[Cytron HAT-MDD10 motorvezérlő]
         ↕ JST fan fejléc
[Active Cooler]
```

#### Standoff rögzítési terv

| Réteg közötti rés | Standoff méret | Csavar típus | Mennyiség |
| :--- | :--- | :--- | :--- |
| Alsó PCB → Felső PCB | 40mm | M3 nylon | 4 db |
| Felső PCB → RPi 5 | 30mm | M2.5 nylon | 4 db |
| RPi 5 → Cytron HAT | 25mm goldpin | – | mellékelve |
| Modulok rögzítése PCB-re | 6–10mm | M3 nylon | ~16 db |

> ⚠️ **Csavarméret figyelem:** Az RPi 5 furatok **M2.5-ösek** (nem M3) – ne erőltesd bele az M3 csavart.

> 💡 **Fém építőkészlet:** Speciális perforált fém profilok (1cm raszteres lyukakkal) nem találhatók meg könnyen AliExpressen. Alternatíva: Double Sided PCB lapok mint szerelőlap, vagy 3D nyomtatott tartók egyedi geometriához.

### 2. Tápellátás – Három független vonal

Az akkumulátorból egy **XT60 4-csatornás Power Distribution Board (PDB)** osztja szét a tápot. Az aksi Deans female csatlakozója egy **Deans male → XT60 male adapter** kábelel csatlakozik a PDB XT60 female bemenetére. A PDB 4 XT60 female kimenetéből 3-at használunk, minden vonalra inline biztosítékkal védve. A 4. kimenet tartalék (jövőbeli bővítéshez).

```
Aksi (female Deans)
    ↓ Deans male → XT60 male adapter
    ↓
XT60 PDB (4-csatornás, 200A, 50.5×25mm)
    ↓ (4× XT60 female kimenet)
├── XT60 → [10A inline fuse] → XL4016 Step-down → 5.1V / 8A → RPi 5 (USB-C)
├── XT60 → [10A inline fuse] → LM2596 Step-down → 5.0V / 2A → PCA9685 V+ → 2× szervómotor
├── XT60 → [25A inline fuse] → Cytron HAT-MDD10 → 2× DC lánctalpas motor (11.1V közvetlen)
└── (tartalék kimenet)
```

> ⚠️ **Közös GND:** Minden vonal GND-je összekötendő (akku –, RPi GND, motorvezérlő GND, PCA9685 GND).

> ⚠️ **Biztosíték helye:** Az inline biztosítékokat a PDB és az egyes modulok közé kell tenni – így minden vonal külön védett, és egy hiba nem érinti a többi vonalat.

**Alkatrészek:**

| Alkatrész | Spec | Megjegyzés |
| :--- | :--- | :--- |
| CNHL LiPo 3S | 11.1V, 5200mAh, 100C, Deans female | ✅ Megvan |
| XT60 4-ch Power Distribution Board | 200A, 50.5×25mm, XT60 I/O | ✅ Megrendelve |
| Deans male → XT60 male adapter | Aksi → PDB bemenet | ✅ Megrendelve |
| XT60 male → blanko kábelek (3 db) | PDB kimenet → modulok | ✅ Megrendelve (XT60 csomag) |
| XL4016 Step-down | Bemenet: 11.1V → Kimenet: 5.1V / 8A | ✅ Megrendelve |
| LM2596 Step-down (voltmérős) | Bemenet: 11.1V → Kimenet: 5.0V / 2A | ✅ Megvan |
| Inline biztosítéktartó (3 db) | ATC/ATO késes, 12V | ❌ Rendelni: AliExpress `inline fuse holder waterproof 12V ATC` |
| Biztosíték betétek | 10A (×2 db) + 25A (×1 db) | ❌ Rendelni: AliExpress `ATC blade fuse assortment` |
| SkyRC IMAX B6 V2 töltő | 6A, 60W, LiPo balance | ✅ Megvan |

### 3. Mozgásvezérlés – DC motorok

*   **Motorok (2 db):** DC 12V, üresjárati áram 100mA, terhelésen ~500mA–1.5A/db.
*   **Motorvezérlő:** Cytron HAT-MDD10 (GPIO HAT, direkt RPi 5-re pattan).
    *   Max 10A folyamatos / 30A csúcs csatornánként – bőven elegendő.
    *   Belső feszültségesés minimális (MOSFET alapú, nem L298N).
    *   **Megjegyzés:** A megvásárolt MX1508 modulok (max 10V) nem kompatibilisek a 11.1V-os LiPo-val, csak kisebb (3.3–10V) motorokhoz alkalmazhatók más projektekben.
*   **Tápellátás:** Közvetlen 11.1V az akkumulátorból, 25A inline biztosítékon át.

**Bekötési táblázat (Cytron HAT-MDD10 → RPi 5 GPIO):**

| Funkció | GPIO (BCM) | Pin |
| :--- | :--- | :--- |
| Bal motor sebesség (PWM) | GPIO 12 | 32 |
| Bal motor irány (DIR) | GPIO 13 | 33 |
| Jobb motor sebesség (PWM) | GPIO 6 | 31 |
| Jobb motor irány (DIR) | GPIO 5 | 29 |

### 4. Kameramozgatás – Szervómotorok

*   **Szervók (2 db):** MG996R, 13kg/cm torque, Metal Gear Digital, 3.0–7.2V, JR/Futaba csatlakozó.
*   **Vezérlő:** PCA9685 16-csatornás PWM driver, I2C interfész.
    *   Időalap: 50Hz (20ms periódus), 0.5ms–2.5ms pulse – illeszkedik az MG996R specifikációhoz.
    *   Felbontás: 12-bit (~4µs lépés).
*   **Tápellátás:** LM2596 Step-down 5V kimenete → PCA9685 V+ terminál blokk.

**PCA9685 bekötés RPi 5-re:**

| PCA9685 láb | Kapcsolat | Pin |
| :--- | :--- | :--- |
| VCC (chip táp) | RPi 3.3V | 1 |
| GND | Közös GND | 6, 9... |
| SDA | GPIO 2 | 3 |
| SCL | GPIO 3 | 5 |
| V+ (szervo táp) | LM2596 5V kimenet | – |

**Szervó bekötés PCA9685-re:**

| Szervó vonal | Szín | PCA9685 csatorna |
| :--- | :--- | :--- |
| Pan szervó signal | Narancs | CH0 |
| Pan szervó táp | Piros | V+ |
| Pan szervó GND | Barna | GND |
| Tilt szervó signal | Narancs | CH1 |
| Tilt szervó táp | Piros | V+ |
| Tilt szervó GND | Barna | GND |

### 5. Szenzorok

#### Ultrahang – HC-SR04P (3 db használatban, 5 db megrendelve, 10 db HC-SR04 tartalék)
*   **Modell:** HC-SR04**P** – a "P" változat 3–5.5V között működik, így az Echo láb **közvetlenül köthető** az RPi 5 GPIO-ra, feszültségosztó nem szükséges.
*   **Elrendezés:** 3 szenzor — **elöl**, **bal-elöl 45°**, **jobb-elöl 45°**. Lefedi a haladási irányt és a sarkokat. Hátra nincs (a robot ritkán tolat, a demón a Teremtő felügyel).
*   **Táp:** 3.3V vagy 5V.

**GPIO kiosztás (3 szenzor):**

| Szenzor | Trig | Echo |
| :--- | :--- | :--- |
| Elöl | GPIO 23 (Pin 16) | GPIO 24 (Pin 18) |
| Bal-elöl 45° | GPIO 25 (Pin 22) | GPIO 8 (Pin 24) |
| Jobb-elöl 45° | GPIO 7 (Pin 26) | GPIO 1 (Pin 28) |

> ℹ️ **HC-SR04 (nem P) tartalék:** Ha mégis az eredeti 5V-os HC-SR04-et használod, az Echo lábra feszültségosztó kell (1kΩ + 2kΩ).

> 📌 **Watchdog:** Mindhárom szenzort a `safety/` modul olvassa külön szálon. Bármelyik küszöb alatt → azonnali `stop()`.

### 6. LED ring
*   **Alkatrész:** WS2812 5050 RGB NeoPixel ring, 5V.
*   **Vezérlés:** SPI módban (`/dev/spidev0.0`) – konfliktus-mentes az RPi 5-ön (elkerüli a PWM/DMA ütközést az audio és motorvezérlővel).
*   **Táp:** RPi 5V pin (kis ringhez elegendő, sok LED esetén külső 5V vonal ajánlott).

### 7. USB perifériák

| Eszköz | Típus | RPi Port |
| :--- | :--- | :--- |
| Wodexun 1080P Webcam (beépített mikrofon) | USB 2.0 | USB 2.0 |
| USB omnidirektcionális mikrofon | USB 2.0 | USB 2.0 |
| A3369 Mini USB Stereo Speaker | USB 2.0 | USB 2.0 |

> ⚠️ **Kettős hangbevitel:** Két mikrofonból az egyiket kell választani (tesztelés alapján). Az omnidirektcionális USB mikrofon hangfelismeréshez általában jobb. A webcam mikrofonját szoftveresen le lehet tiltani ALSA konfigurációban.

> 💡 **USB max áram:** `/boot/firmware/config.txt`-be hozzáadandó: `usb_max_current_enable=1`

---

## 📌 Teljes GPIO kiosztás

| GPIO (BCM) | Pin | Funkció | Eszköz |
| :--- | :--- | :--- | :--- |
| GPIO 2 | 3 | I2C SDA | PCA9685 |
| GPIO 3 | 5 | I2C SCL | PCA9685 |
| GPIO 5 | 29 | DIR2 output | HAT-MDD10 jobb motor irány |
| GPIO 6 | 31 | PWM2 output | HAT-MDD10 jobb motor sebesség |
| GPIO 12 | 32 | PWM1 output | HAT-MDD10 bal motor sebesség |
| GPIO 13 | 33 | DIR1 output | HAT-MDD10 bal motor irány |
| GPIO 23 | 16 | Trig output | HC-SR04P elöl |
| GPIO 24 | 18 | Echo input | HC-SR04P elöl |
| GPIO 25 | 22 | Trig output | HC-SR04P bal-elöl 45° |
| GPIO 8 | 24 | Echo input | HC-SR04P bal-elöl 45° |
| GPIO 7 | 26 | Trig output | HC-SR04P jobb-elöl 45° |
| GPIO 1 | 28 | Echo input | HC-SR04P jobb-elöl 45° |
| SPI0 (GPIO 10) | 19 | SPI MOSI | WS2812 LED ring |
| – | JST fan | PWM fan | Active Cooler |

---

## 🖥️ Szoftver Stack & AI

### 1. Operációs rendszer
*   **OS:** Raspberry Pi OS 64-bit Lite (**Debian Bookworm** alapú – nem Ubuntu).
*   **Telepítés:** RPi Imager (előre konfigurált Wi-Fi, SSH pubkey és user).

### 2. AI Modellek — DÖNTÉS: Llama (8B cloud / 3B edge)

> ✅ **STÁTUSZ: az A/B lezárult.** A saját magyar persona-benchmark (`training/persona_benchmark.json` + `ertekelo_sablon.md`) alapján a **Llama család győzött** — a Llama erősebb magyart adott, mint a Qwen mindkét méretben. **Hibrid, aszimmetrikus felállás:** felhőben **Llama 3.1 8B**, edge-en **Llama 3.2 3B** (fine-tunolva, Q4_K_M).

**Az A/B tanulsága (3B → 7-8B benchmark):**

| Méret | Eredmény |
| :--- | :--- |
| 3B (Qwen 2.5 / Llama 3.2) | Magyar nyelvileg törött / hallucináló — a 3B a magyar plafonja, demóra nem elég. |
| 7B Qwen | Jobb, de a magyarja még gyengébb, mint a Llamáé. |
| **Llama 3.1 8B (győztes)** | Első demó-közeli magyar persona — koherens, hangban van. |

> 🔑 **Két külön probléma vált szét:** a **magyar/persona = méret** (a 8B megoldja); a **tool-calling = adat** (minden méretnél gyenge maradt, mert a datasetnek csak ~6%-a tool-példa — ez dataset-bővítéssel javul, NEM modell-cserével). A tény-hallucinációt pedig **RAG** kezeli (tények → RAG; stílus/érték → fine-tune).

| Eszköz | Modell | Szerep | Kvantálás |
| :--- | :--- | :--- | :--- |
| Cloud (Hetzner Cloud **CAX31**, ARM CPU) | **Llama 3.1 8B** | **Csak inferencia** (Ollama), on-demand | Q4_K_M |
| Edge (RPi 5, ARM CPU) | **Llama 3.2 3B** | Offline fallback inferencia | Q4_K_M (~2–2.5 GB RAM) |

> 🔄 **Fontos váltás: GEX44 → Hetzner Cloud CAX31.** A GEX44 egy GPU-s **dedikált** szerver — havi fix díj, NEM indítható/törölhető API-ból. A `hcloud` CLI csak Hetzner **Cloud** instance-okat kezel. Mivel a 3B Q4 modell CPU-n is jól fut, egy **CAX31** (8 ARM vCPU, 16 GB) Cloud szerver elég — óradíjas, Terraformmal on-demand indítható/törölhető. Ez a tényleges „fizess csak amikor használod".

> 🧩 **Aszimmetrikus hibrid:** a felhő nagyobb modellt (8B) futtat, mint az edge (3B) — a két hely viselkedése tehát KÜLÖNBÖZIK: az edge tudatosan egy „kevésbé ékesszóló, de szuverén" fallback. (Mindkét hely ARM + Ollama, a stack azonos; csak a modellméret és a minőség/sebesség tér el. Ez felülírja a korábbi „ugyanaz a GGUF fut mindkét helyen" tervet.)

**Szerver-méret döntés (tesztek döntik el):**

| | CAX31 (kiindulás) | CAX41 (upgrade ha kell) |
| :--- | :--- | :--- |
| vCPU / RAM | 8 / 16 GB | 16 / 32 GB |
| Becsült tok/s (3B Q4) | ~10–18 | ~18–30 |
| Mikor | egyetlen beszélgetés, demó | hosszú válaszok / párhuzamos kérések |

> ⚠️ **Sebesség-realitás a 8B-re:** a fenti tok/s a **3B**-re vonatkozik. A **8B Q4 CPU-n mindenhol lassú** — egy erős x86 laptopon is csak ~4-5 tok/s, a CAX31 ARM CPU-ján hasonló vagy lassabb. A demón ez vállalható, mert a válaszok rövidek (tömör persona) és a Teremtő élőben tolmácsol — ez időt ad. Igazán snappy 8B **GPU**-t igényelne, ami a hcloud Cloud API-n nem elérhető (ezért esett ki a GEX44 is); a CAX = CPU-only. Az **edge 3B** marad a gyorsabb (~2-5 tok/s a Pin) offline út. A szerver-méret egysoros változtatás a Terraform variable-ben.

*   **Egységes modell előnye:** Egyetlen fine-tuning, azonos persona mindkét eszközön. A LoRA adapter (vagy merge-elt GGUF) megy mindkét helyre.
*   **A cloud szerver szerepe:** **Kizárólag inferencia** Ollamán keresztül, on-demand (Terraform apply/destroy). A fine-tuning NEM itt fut (Google Colab).
*   **Fallback logika (a Python orchestrator kezeli):**
    *   Cloud elérhető (WireGuard up) → cloud 3B (gyorsabb, nagyobb kontextus)
    *   Cloud nem elérhető → RPi 5 helyi 3B (Q4_K_M, offline)
    *   Kritikus hiba → „safe mode" (előre definiált válaszok, mozgás tiltva)

### 3. Fine-tuning – Google Colab (ingyenes T4)

*   **Hol:** Google Colab, ingyenes T4 GPU. (A Hetzner Cloud szerver CPU-only, nem fine-tunol — csak inferál. Kinőve: RunPod / Vast.ai RTX 4090.)
*   **Library:** Unsloth (2–5× gyorsabb, kevesebb VRAM, natív Llama 3.1/3.2 támogatás). A 7-8B QLoRA is befér a T4-be (batch=1, grad_accum=8).
*   **Módszer:** QLoRA, 4-bit base + LoRA adapterek (rank r=16 ajánlott kiindulás).
*   **Dataset:** 630 példa (lásd `training/dataset/`), magyar nyelvű, Alpaca formátum.
    *   Train/val split: 567 / 63 (90/10).
    *   Kategóriák: etika (289), kultura (100), tech (100), hacktivity (49), identity_szabi (25), motion_toolcall (25), yotengrit (15), oracle_routing (15), wifi_scan (12).
*   **Becsült idő:** ~30–50 perc/futás T4-en (603 példa, 2–3 epoch). Egy Colab session belefér.
*   **Hiperparaméter:** a `--preset gentle` (epochs=1, lr=5e-5, r/alpha=8, dropout=0.05) vált be — a v1 (epochs=2–3, lr=2e-4, r=16) **túltanult** (törött magyar). A tényleges nyereség a **8B méret** + a tömörebb dataset volt, nem a recept finomhangolása.
*   **Fontos:** Ne hajszold az alacsony loss-t (overfitting → robotikus, ismétlő válaszok). Validation set-en mérj, 2 epoch gyakran jobb mint 3.
*   **Export:** GGUF (Q4_K_M edge-re, Q8/f16 cloud-ra) → Ollama Modelfile.

### 4. Hang-pipeline (offline, RPi 5-ön)

A teljes hang-lánc offline fut a szuverenitás jegyében:

```
1. WAKE WORD: "Szabi"  →  openWakeWord (saját betanított modell)
2. FELVÉTEL          →  USB mikrofon + VAD (Voice Activity Detection)
3. STT (magyar)      →  Whisper.cpp (base vagy small modell)
4. LLM               →  Llama 3.1 8B (cloud) / Llama 3.2 3B (edge) + LoRA (fallback szerint)
                        → persona válasz + opcionális <tool> blokk
5a. TTS (női hang)   →  Piper (hu_HU-anonymous-medium)
5b. VEZÉRLÉS         →  a <tool> blokkot a Python orchestrator végrehajtja
```

| Komponens | Megoldás | Megjegyzés |
| :--- | :--- | :--- |
| Wake word | **openWakeWord** | Saját „Szabi" wake word betanítható, nyílt/ingyenes |
| STT | Whisper.cpp (base/small) | Magyar nyelv, offline; sebesség/pontosság tesztelendő RPi 5-ön |
| TTS | Piper `hu_HU-anonymous-medium` | Offline, női magyar hang; pitch/sebesség hangolható fiatalosabbra |

> ⚠️ **Erőforrás:** STT + LLM + TTS együtt ~5.5 GB RAM a 8 GB-ból. Ezért a nehéz LLM-inferencia elsősorban a cloud-ra megy (ha van net), és csak offline fut a teljes stack az RPi-n.

### 5. Mozgásvezérlés – Réteges architektúra (tool-calling)

**Alapelv:** Az LLM SOHA nem vezérli közvetlenül a motorokat. Három réteg:

```
1. LLM (a „lélek")      → szándék-felismerés + persona
                          kimenet: "Megyek, Teremtő! <tool>move forward 2</tool>"
2. Vezérlő kódréteg     → a <tool> blokkot determinisztikus GPIO/PWM
   (a „test", Python)     parancsokká fordítja (Cytron HAT)
3. Biztonsági watchdog  → HC-SR04P szenzorok külön szálon; akadálynál
   (a „reflex")           AZONNAL megáll, az LLM-et meg sem kérdezve
```

*   **Architektúra:** Egyszerű Python **threading/asyncio** (NEM ROS 2 – lásd roadmap). Kevesebb függőség, gyorsabb fejlesztés, RPi 5-re elég.
*   **Tool-formátum:** pozicionális `<tool>NAME érték1 érték2</tool>` – zárójel/idézőjel NÉLKÜL (pl. `<tool>move forward 2</tool>`, `<tool>turn left 90</tool>`, `<tool>stop</tool>`). A kis modell ezt sokkal megbízhatóbban adja, mint a `fn(k=v)` formát; a parse egyértelmű, mert az érték-tartományok diszjunktak (szám = távolság/fok, szó = irány/sebesség/mód, `until` = jelölő). A `request_navigation_help` az egyetlen szabad-szöveges tool: a név utáni teljes maradék a cél (lehet szóközös). A parser toleráns az extra szóközre.
*   **Ismert tool-ok (a dataset alapján):** `move()`, `turn()`, `stop()`, `camera()`, `set_speed()`, `set_mode()`, `request_navigation_help()`, `scan_wifi()`, `set_oracle()`.
*   **`scan_wifi()` tool:** `nmcli -t -f SSID,SIGNAL,SECURITY dev wifi` kimenetét adja vissza. Az LLM personás kommentárral sorolja fel a hálózatokat a biztonsági szintjükkel (nyílt / WEP / WPA2 / WPA3). **Csak olvasás** — a tool SOHA nem csatlakozik hálózatra (nincs injection-felület, nincs jelszó-kezelés).
*   **Biztonsági watchdog:** Független szál, ami az ultrahang-szenzorokat olvassa. Ha a távolság < küszöb → `stop()` azonnal, függetlenül az LLM-től. Ez egyben a Hacktivity biztonsági üzenet alátámasztása.

> 📌 **ROS 2 roadmap:** A jelenlegi PoC Python szálakon fut. A ROS 2-re portolás a következő iteráció terve (nem a Hacktivity scope-ja) – a réteges felépítés ezt később megkönnyíti.

### 6. „Tudók" — opcionális LLM routing (CSAK családi mód, NEM a demón)

> ⚠️ **STÁTUSZ: opcionális, alapból kikapcsolva a demóhoz.** Ez a funkció megtöri a szuverenitás-elvet (külső API-függés), ezért **kizárólag a családi/szórakoztató módban** aktív. A Hacktivity demón `mode: sovereign` (kikapcsolva).

**Koncepció:** Ha Szabi nehéz kérdést kap, „megpuskázza" egy nagyobb külső modelltől (alapból Anthropic Opus 4.8), de a választ NEM nyersen adja tovább — **megszűri a saját Yotengrit-értékrendjén**. Mindig hozzátesz saját nézőpontot, és finoman jelzi, hogy a Tudóktól kérdezett. Az Opus adja a nyers tudást, Szabi adja a nézőpontot.

**Architektúra (orchestrator-vezérelt — a megbízhatóbb):**

```
1. Kérdés érkezik → orchestrator értékeli (hibrid trigger)
2. Ha „puskázás" kell:
   a. Orchestrator hívja a külső API-t (Opus 4.8) → NYERS válasz
   b. Orchestrator visszaadja Szabinak: "[TUDÓK VÁLASZA: {nyers}]
      Foglald össze a saját értékrended szerint, Teremtő."
   c. Szabi (3B + fine-tuning) megszűri → persona-hangú, árnyalt válasz
3. Ha nem kell → Szabi simán válaszol helyben
```

> Miért orchestrator és nem a 3B modell vezényli: a kétlépéses tool-flow-t (hívás → válasz újrafeldolgozása) a kis modell gyakran elrontja. Az orchestrator determinisztikus, kezeli a hibát (nincs net), és garantálja a persona-szűrést.

**Hibrid trigger (mikor fordul a Tudókhoz):**
*   **Kód-küszöb (orchestrator):** kérdéshossz > N szó (config: `trigger_word_count`), kulcsszavak („magyarázd el", „számold ki", „hasonlítsd össze"), vagy a helyi modell bizonytalansága.
*   **Szabi kérheti (LLM):** a fine-tuningban megtanult `<puska/>` jelet bocsát ki, ha úgy érzi, meghaladja a tudása. Az orchestrator elkapja és aktiválja.

**Persona-szűrés szabályai (a fine-tuning tanítja, lásd `oracle_routing` dataset kategória):**
*   **Mindig** tegyen hozzá saját (Yotengrit) nézőpontot — egyetértés, árnyalás vagy vita.
*   **Finoman** jelezze a puskázást („úgy hallom a tudóktól", „a nagy könyv szerint") — ne nyersen („az Opus szerint").
*   Példa: a tudatosság-kérdésnél idézi a tudományos konszenzust, majd a Yotengrit nézőpontját adja (a tudat szüli az anyagot, nem fordítva).

**Kapcsoló — config + két hangparancs:**

```yaml
oracle:
  enabled: false               # alapból KI (demó = sovereign mód)
  provider: "anthropic"        # konfigurálható: anthropic / openai / ollama
  model: "claude-opus-4-8"     # konfigurálható
  api_key_env: "ANTHROPIC_API_KEY"
  trigger_word_count: 25       # kód-küszöb
  mode: "sovereign"            # "sovereign" = KI, "extended" = BE
```

*   **„Szabi, puskázz"** → `set_oracle(enabled=true)` → "Ahogy parancsolod, Teremtő, kérdezem a tudókat, ha elakadnék."
*   **„Szabi, ne puskázz"** → `set_oracle(enabled=false)` → "Becsukom a nagy könyvet, csak a magam fejével felelek."

> 💡 **Provider rugalmasság:** a `provider: "ollama"` beállítással a „Tudók" lehet egy nagyobb **helyi** modell is (pl. egy 14B a CAX41-en) — így a puskázás is maradhat szuverén, ha akarod. Alapból viszont az Opus 4.8 a legokosabb válasz.

### 7. Infrastruktúra mint kód (IaC)
*   **Terraform:** Hetzner Cloud erőforrások – CAX31 ARM szerver (on-demand apply/destroy), tűzfal (csak SSH + WireGuard portok), privát hálózat. A szerver-típus variable-ben (CAX31 ↔ CAX41 egysoros váltás).
*   **Ansible:** Zero-touch provisioning a CAX szerveren:
    *   Docker + Ollama telepítés
    *   A fine-tunolt GGUF modell betöltése Ollamába (Modelfile)
    *   WireGuard szerver konfiguráció + kulcscsere
    *   Tűzfal és fail2ban
*   **VPN:** WireGuard alagút (Hetzner: 10.0.0.1 ↔ RPi 5: 10.0.0.2), systemd-vel a RPi oldalon.

### 8. Hálózati csatlakozás (helyszíni)

**Elsődleges: USB LTE modem** (ajánlott a konferencia-környezetre)
*   **Típus:** Huawei E3372 vagy hasonló HiLink LTE stick — a legjobban támogatott Raspberry Pi-n. HiLink módban virtuális ethernetként jelenik meg, zéró konfiggal felmegy.
*   **SIM:** olcsó feltöltőkártyás, pár GB adat elég (egy LLM kérés/válasz csak pár száz KB).
*   **Indok:** független a megbízhatatlan konferencia-WiFitől; a hibrid cloud-edge architektúra (Hetzner elérés) stabilabb; a "saját, független netkapcsolat" maga is szuverenitás-üzenet.

**Tartalék: kézi WiFi-beállítás**
*   **Telefon hotspot trükk:** a Pi előre ismeri a telefonod hotspotját → helyszínen bekapcsolod → SSH-zol rá telefonon át → beállítod a konferencia WiFit `nmcli`-vel.
*   **USB-C–Ethernet + laptop:** közvetlen kábeles kapcsolat, SSH link-local címen, nincs WiFi-függőség.

> 📌 **A robot NEM csatlakozik hangutasításra hálózatra** (biztonsági döntés — lásd Meghozott döntések). A hálózat-beállítás mindig kézi, biztonságos csatornán. A `scan_wifi()` tool csak olvas/listáz.

> 💡 **Bombabiztos demó:** LTE modem (elsődleges net) + offline edge LLM fallback együtt = a net kiesése sem végzetes, a robot helyben tovább gondolkodik.

### 9. Repo struktúra (monorepo)

```
free-droid/
├── docs/
│   └── free-droid.md              # ez a dokumentum
├── infra/                         # IaC
│   ├── terraform/                 # Hetzner Cloud CAX31 provisioning (on-demand)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── ansible/                   # szerver konfiguráció
│       ├── playbook.yml
│       ├── roles/
│       │   ├── docker/
│       │   ├── ollama/
│       │   └── wireguard/
│       └── inventory.ini
├── robot/                         # RPi 5 vezérlő szoftver
│   ├── orchestrator/              # fő async loop, fallback logika
│   ├── motion/                    # vezérlő kódréteg (Cytron HAT)
│   ├── safety/                    # ultrahang watchdog (külön szál)
│   ├── voice/                     # wake word + STT + TTS pipeline
│   ├── llm/                       # LLM kliens (cloud/edge fallback)
│   ├── oracle/                    # „Tudók" routing — külső API + persona-szűrés (opcionális)
│   ├── tools/                     # tool-calling parser + handlerek
│   └── config/                    # GPIO pinout, küszöbök, hangok
├── training/                      # fine-tuning
│   ├── dataset/
│   │   ├── freedroid_full.json    # teljes 630 példa
│   │   ├── train.jsonl            # 567 példa
│   │   ├── val.jsonl              # 63 példa
│   │   └── expansion_only.json    # a 92 új példa külön (persona+yotengrit+motion+wifi+oracle)
│   ├── colab_finetune.ipynb       # Unsloth QLoRA notebook
│   ├── persona_benchmark.json     # 25 kérdés az A/B modell-teszthez
│   ├── ertekelo_sablon.md         # pontozó sablon (Llama vs Qwen)
│   └── Modelfile                  # Ollama export konfiguráció
└── README.md
```

---

## 🛒 Alkatrész státusz

| Alkatrész | Státusz |
| :--- | :--- |
| CNHL LiPo 3S 5200mAh 100C, Deans female | ✅ Megvan |
| Aluminum lánctalpas váz + 2× DC motor 12V | ✅ Megvan |
| Raspberry Pi 5 (8GB) + Active Cooler | ✅ Megvan |
| PCA9685 16-ch PWM driver | ✅ Megvan |
| MG996R szervómotor (2 db) | ✅ Megvan |
| HC-SR04 ultrahang szenzor (10 db, 5V) | ✅ Megvan – tartalék, feszültségosztóval használható |
| HC-SR04P ultrahang szenzor (5 db, 3–5.5V) | ✅ Megérkezett |
| LM2596 DC-DC Step-down (voltmérős) | ✅ Megvan |
| XL4016 DC-DC Step-down 8A 200W | ✅ Megérkezett |
| XT60 4-csatornás Power Distribution Board | ✅ Megérkezett – male/female párosítás tesztelve, OK |
| XT60 ↔ Deans adapter + pigtail kábelek | ✅ Megérkezett – csatlakozók illeszkednek |
| Double Sided PCB Prototype Board (10 db) | ✅ Megérkezett |
| Perfboard 4×6cm (5 db) | ✅ Megérkezett |
| M3 nylon standoff 40mm (20 db) | ✅ Megérkezett |
| M2.5 nylon standoff 30mm (50 db) | ✅ Megérkezett |
| Inline biztosítéktartó 14AWG ATO/ATC (6 db) | ✅ Megérkezett |
| Biztosíték betét 10A ATO (piros, 10 db) | ✅ Megérkezett – Step-down vonalakra |
| Biztosíték betét 25A ATO (átlátszó, 10 db) | ✅ Megérkezett – motor vonalra, méret OK |
| Velcro akkupánt (L200/250/300mm, 5 db) | ✅ Megérkezett |
| 12V / 6A DC tápegység (EU plug) | ✅ Megérkezett |
| SkyRC IMAX B6 V2 töltő | ✅ Megvan |
| Wodexun 1080P Webcam | ✅ Megvan |
| USB omnidirektcionális mikrofon | ✅ Megvan |
| A3369 Mini USB Stereo Speaker | ✅ Megvan |
| Breadboard MB102 400+830 + Dupont kábelek | ✅ Megvan |
| WS2812 5050 RGB LED ring | ✅ Megvan |
| MX1508 motorvezérlő (6 db) | ✅ Megvan – ⚠️ NEM használható 11.1V LiPo-val (max 10V), kis motorokra félretéve |
| **Cytron HAT-MDD10 motorvezérlő** | ✅ Megérkezett – 25mm goldpin strip mellékelve |
| **2DOF Pan-Tilt gimbal keret MG996R-hez** | ❌ **RENDELD MEG ELŐSZÖR** (szűk keresztmetszet, szállítási idő) – AliExpress: `pan tilt bracket MG996R aluminum 2DOF` |
| **USB LTE modem (Huawei E3372 HiLink)** | ❌ **Rendelni kell** – elsődleges netkapcsolat a helyszínen + pár GB-os feltöltőkártyás SIM |

---

## ✅ Megvalósítási Checklist

A feladatok fázisokra bontva. A `[ ]` jelölés végrehajtható; a Claude Code ezeket sorban veheti.

### 🔗 Függőségi térkép & párhuzamosíthatóság

A projekt **két fő ága párhuzamosan haladhat** (fontos a heti 2-5 órás keret miatt — amíg alkatrészre vársz vagy hardvert szerelsz, a szoftver/fine-tuning ág is mozoghat):

```
   HARDVER ÁG (fizikai)                SZOFTVER ÁG (gép előtt)
   ───────────────────                 ──────────────────────
   F1.1 Tápellátás teszt               F2 Fine-tuning (Colab)
        │                                   │  (csak laptop + net kell)
   F1.2 Vezérlés bekötés                    │
        │                              F3 Cloud infra (Terraform/Ansible)
   F1.3 Közös GND + táp                     │  (csak laptop + net kell)
        │                                   │
   F1.4 Mechanika ◄── (2DOF keret       ┌───┘
        │            megrendelés!)       │
   F1.5 HW smoke-test                    │
        │                                │
        └──────────────┬─────────────────┘
                        ▼
              F4 RPi szoftver (robot/)
              ⚠️ IGÉNYLI: kész hardver (F1.5) + fine-tunolt modell (F2) + cloud (F3)
                        │
                        ▼
              F5 Integráció & demó-próba
```

**Kritikus út (a leghosszabb lánc):** F1.1 → F1.2 → F1.3 → F1.5 → F4 → F5
**Azonnal indítható, bárkitől függetlenül:** F2 (fine-tuning), F3 (cloud infra), 2DOF keret megrendelése
**Szűk keresztmetszet:** a 2DOF pan-tilt keret megrendelése — add le ELŐSZÖR, mert szállítási idő van rajta (F1.4 erre vár).

**Függőségek fázisonként:**
| Fázis | Függ ettől | Párhuzamosítható ezzel |
| :--- | :--- | :--- |
| F1.1 Tápellátás | — (minden megvan) | F2, F3 |
| F1.2 Vezérlés | F1.1 | F2, F3 |
| F1.3 GND + táp | F1.2 | F2, F3 |
| F1.4 Mechanika | 2DOF keret megérkezése | F1.1–F1.3, F2, F3 |
| F1.5 HW smoke-test | F1.3 + F1.4 | F2, F3 |
| F2 Fine-tuning | dataset (✅ kész) | teljes HARDVER ág, F3 |
| F3 Cloud infra | Hetzner account | teljes HARDVER ág, F2 |
| F4 RPi szoftver | **F1.5 + F2 + F3** | — (itt összeér minden) |
| F5 Integráció | F4 | — |

> 💡 **Stratégia a szűk időkerethez:** Kezdd egyszerre az F1.1-et (hardver) ÉS az F2-t (Colab fine-tuning) — előbbi fizikai, utóbbi gép előtti munka, nem zavarják egymást. A 2DOF keretet rendeld meg ma. Mire a hardver és a modell kész, az F3 (cloud) is megvan, és minden találkozik az F4-nél.

### FÁZIS 1 — Hardver összeszerelés & tesztek
> 🔗 *Indítható azonnal (F1.1). Párhuzamos: F2, F3. F1.4 a 2DOF keretre vár.*

**1.1 Tápellátás (Cytron előtt is elvégezhető)**
- [ ] XL4016 Step-down beállítása **5.1V**-ra (terhelés nélkül, multiméterrel)
- [ ] LM2596 Step-down beállítása **5.0V**-ra (multiméterrel)
- [ ] XL4016 **terheléses teszt** (ismert terhelés rákötése, tartja-e az 5.1V-ot — olcsó klónok leeshetnek)
- [ ] PDB bemenet összekötése: aksi → Deans/XT60 adapter → PDB (male/female már tesztelve ✅)
- [ ] 3× inline biztosíték beépítése a PDB és a modulok közé (XL4016: 10A, LM2596: 10A, Cytron: 25A)
- [ ] Kábelkötések: WAGO 221 vagy forrasztás+zsugorcső (NE sima csavaros sorkapocs — rezgés!)

**1.2 Vezérlés bekötése**
- [ ] Cytron HAT-MDD10 felhelyezése a 25mm hosszított goldpin strippel (Active Cooler ütközés elkerülése)
- [ ] Cytron + Active Cooler fizikai illeszkedés ellenőrzése
- [ ] DC motorok bekötése a Cytron A1/A2, B1/B2 kimenetekre
- [ ] PCA9685 bekötése: VCC→3.3V, SDA→GPIO2, SCL→GPIO3, GND, V+→LM2596 5V
- [ ] 2× MG996R szervó a PCA9685 CH0 (pan) és CH1 (tilt) csatornákra
- [ ] HC-SR04P (elöl): VCC→3.3V, Trig→GPIO23, Echo→GPIO24 (közvetlen, nincs feszültségosztó)
- [ ] WS2812 LED ring: SPI módban (`/dev/spidev0.0`), 5V táp

**1.3 Közös GND & táp-véglegesítés**
- [ ] **KRITIKUS:** közös GND ellenőrzése — akku(–), RPi GND, Cytron GND, PCA9685 GND mind összekötve
- [ ] `/boot/firmware/config.txt`: `usb_max_current_enable=1` és SPI engedélyezés
- [ ] **Pi 5 táp teszt:** 5.1V mérése a Pi rákötése ELŐTT

**1.4 Mechanika**
- [ ] 2DOF pan-tilt gimbal keret megrendelése (MG996R kompatibilis alu) + összeszerelés
- [ ] Webkamera rögzítése a gimbal tetejére (1/4" adapter vagy 3D nyomtatott tartó)
- [ ] PCB stack összeállítása standoff-okkal (40mm M3 a PCB-k közt, 30mm M2.5 a Pi alatt)
- [ ] Akku rögzítése velcro pánttal a váz közepén

**1.5 Hardver smoke-test (szoftver nélkül)**
- [ ] Motor teszt: egyszerű GPIO szkript, mindkét motor előre/hátra
- [ ] Szervó teszt: PCA9685 sweep CH0/CH1
- [ ] HC-SR04P teszt: távolságmérés kiírása
- [ ] USB eszközök felismerése: `lsusb`, `arecord -l`, `aplay -l`
- [ ] USB LTE modem teszt: HiLink stick felmegy-e (virtuális ethernet), van-e net a SIM-en
- [ ] Mikrofon-választás: webcam vs. omnidirekcionális (tesztelés, a jobbik marad; másik letiltása ALSA-ban)

### FÁZIS 2 — Fine-tuning (Google Colab)
> 🔗 *Indítható azonnal (dataset kész). Párhuzamos a teljes hardver ággal és F3-mal. Csak laptop + net kell.*

- [ ] **Tanulás:** Unsloth hivatalos notebook (Qwen 2.5 3B vagy Llama 3.2 3B) végigfuttatása VÁLTOZTATÁS NÉLKÜL (a folyamat megértése)
- [ ] A 4 kulcs-hiperparaméter megértése (epochs, lr, LoRA rank, max_seq_length)
- [ ] Saját `train.jsonl` / `val.jsonl` betöltése a notebookba
- [ ] **A/B teszt — 1. modell:** Qwen 2.5 3B fine-tuning (r=16, epochs=2, lr=2e-4)
- [ ] **A/B teszt — 2. modell:** Llama 3.2 3B fine-tuning (UGYANAZ a paraméter, dataset)
- [ ] Mindkét modell exportálása GGUF Q4_K_M-be
- [ ] `persona_benchmark.json` 25 kérdése mindkét modellen lefuttatva
- [ ] Pontozás az `ertekelo_sablon.md` szerint (6 dimenzió, 1-5 skála)
- [ ] Sebesség-mérés RPi 5-ön mindkét modellnél (tok/s, RAM)
- [ ] **Modell-választás véglegesítése** az összesítő alapján → MD + README frissítése
- [ ] Kiértékelés: a győztes vanilla vs. fine-tunolt összevetése (persona előjön-e?)
- [ ] Overfitting-ellenőrzés a validation set-en (ha robotikus/ismétlő → kevesebb epoch)
- [ ] Szükség esetén 1-2 iteráció (epoch, dataset-bővítés a gyenge kategóriákban)
- [ ] Végső export GGUF-ba: Q4_K_M (edge) + Q8/f16 (cloud)
- [ ] Ollama `Modelfile` készítése (system prompt + paraméterek)
- [ ] Lokális teszt Ollamával (persona + tool-formátum helyes-e)
- [ ] **„Red team" tesztkör (KÖTELEZŐ a szabad demó miatt):** váratlan, provokatív, off-topic kérdések — hol esik ki a persona? Gyenge pontoknál célzott példa-bővítés.

> ⚠️ Ha a `motion_toolcall` kategória bizonytalan a tesztnél (rossz `<tool>` formátum), bővítsd 25→50-60 példára és tréningelj újra.

### FÁZIS 3 — Cloud infrastruktúra (Terraform + Ansible)
> 🔗 *Indítható azonnal (Hetzner account kell). Párhuzamos a teljes hardver ággal és F2-vel.*

- [ ] **Terraform:** CAX31 ARM szerver provisioning (`infra/terraform/`), on-demand apply/destroy, szerver-típus variable (CAX31 ↔ CAX41)
- [ ] Terraform: tűzfal (csak SSH + WireGuard UDP port), privát hálózat
- [ ] **On-demand workflow teszt:** `terraform apply` → szerver feláll → `terraform destroy` → eltűnik (költség csak amíg fut)
- [ ] **Ansible:** Docker telepítés a CAX szerveren
- [ ] Ansible: Ollama telepítés + a GGUF modell betöltése (ARM build)
- [ ] Ansible: WireGuard szerver konfig + kulcsgenerálás/csere
- [ ] Ansible: fail2ban + SSH hardening
- [ ] Inferencia smoke-test: HTTP kérés az Ollama API-hoz a szerveren
- [ ] Sebesség-mérés CAX31-en (tok/s), döntés: elég-e vagy CAX41 kell

### FÁZIS 4 — RPi 5 vezérlő szoftver (Python, `robot/`)
> 🔗 *⚠️ IGÉNYLI: F1.5 (kész hardver) + F2 (fine-tunolt modell) + F3 (cloud). Itt ér össze a két ág.*

**4.1 Alaprétegek** *(4.1 és 4.2 egymással párhuzamosíthatók — független modulok)*
- [ ] `config/`: GPIO pinout, távolság-küszöbök, hang-paraméterek központi configba *(ezt csináld ELŐSZÖR — a többi modul innen olvas)*
- [ ] `motion/`: Cytron HAT vezérlő osztály (move, turn, stop, set_speed) — lgpio alapon *(függ: config)*
- [ ] `safety/`: ultrahang watchdog külön szálon, `stop()` küszöb alatt *(függ: config; tesztelhető motion nélkül is)*
- [ ] `tools/`: `<tool>...</tool>` parser + handler-ek (robusztus, hibatűrő) *(függ: motion — a handlerek azt hívják)*
- [ ] `tools/`: `scan_wifi()` handler — `nmcli` olvasás, biztonsági szint parse (csak olvas, sosem csatlakozik) *(független)*
- [ ] `oracle/`: „Tudók" routing (OPCIONÁLIS, alapból KI) — hibrid trigger (`<puska/>` jel + kód-küszöb), külső API kliens (Opus 4.8, provider konfigurálható), persona-szűrés (a nyers választ Szabin átengedi), `set_oracle()` hangkapcsoló *(függ: llm/, tools/)*

**4.2 LLM & hang** *(a voice/ almodulok egymástól függetlenek, külön fejleszthetők)*
- [ ] `llm/`: kliens cloud (WireGuard→Ollama) és edge (helyi Ollama) fallbackkel *(függ: F2 modell + F3 cloud)*
- [ ] `voice/`: openWakeWord „Szabi" wake word betanítása + integráció *(független)*
- [ ] `voice/`: Whisper.cpp STT (magyar) integráció *(független)*
- [ ] `voice/`: Piper TTS (`hu_HU-anonymous-medium`) integráció, pitch/sebesség hangolás fiatalosabbra *(független)*
- [ ] `voice/`: VAD (mikor fejezte be a beszédet) *(független)*

**4.3 Orchestrator & integráció** *(IGÉNYLI: 4.1 + 4.2 minden modul kész)*
- [ ] `orchestrator/`: fő async loop (wake→STT→LLM→TTS + tool végrehajtás párhuzamosan) *(függ: minden 4.1 + 4.2 modul)*
- [ ] Fallback logika: cloud elérhetőség detektálása, edge-re váltás *(függ: llm/)*
- [ ] „Safe mode": kritikus hiba esetén mozgás tiltva, előre definiált válasz *(függ: motion, safety)*
- [ ] WS2812 státuszjelzés (figyel / gondolkodik / beszél / hiba) *(független, bármikor)*
- [ ] systemd service-ek (orchestrator, WireGuard kliens) auto-indításhoz *(utolsó lépés)*

### FÁZIS 5 — Integráció & Hacktivity demó-próba
> 🔗 *IGÉNYLI: F4 kész. Ez a záró fázis.*

- [ ] Teljes lánc teszt offline (edge LLM): „Szabi, gyere ide" → mozgás + válasz
- [ ] Teljes lánc teszt online (cloud LLM, WireGuard)
- [ ] Cloud-kiesés szimuláció: WireGuard leállítása menet közben → edge fallback működik-e
- [ ] Biztonsági watchdog éles teszt: akadály a robot elé → azonnali megállás
- [ ] Demó-forgatókönyv begyakorlása (a Teremtő kérdez magyarul, tolmácsol angolra)
- [ ] Hangerő/akusztika teszt konferencia-környezetre (zajos terem)
- [ ] Akku-üzemidő mérése teljes terhelésen (LLM + mozgás + hang)
- [ ] Tartalék terv: ha a WiFi megbízhatatlan a helyszínen → tiszta offline demó

---

## 🎯 Meghozott döntések (lezárva)

*   **Navigáció:** Nincs SLAM/térképezés. **Reaktív mozgás** — parancsra fordul/megy, ultrahanggal megáll akadálynál. A robot bevallja, ha nem ismer egy útvonalat (a dataset így kezeli). *Indok: a SLAM önmagában több hónapos projekt, felemésztené a Hacktivity-keretet.*
*   **Szenzorok:** **3 db HC-SR04P** — elöl + bal-elöl 45° + jobb-elöl 45° (6 GPIO). Hátra nincs.
*   **Demó:** **Teljes persona, szabad kérdések** (nem kötött forgatókönyv). A 603 példás dataset elbírja. → **Kötelező a fine-tuning utáni „red team" tesztkör** (lásd Fázis 2), hogy lásd hol esik ki a persona váratlan/provokatív kérdéseknél.
*   **TTS-hang:** `hu_HU-anonymous-medium`, fiatalosabb karakterhez **pitch-hangolás a hangmintán** (tesztelési feladat, Fázis 4.2).
*   **Nyelv:** Magyar-only. A Hacktivity előadáson a Teremtő tolmácsol angolra — ez az üzenet része, nem korlát.
*   **„Tudók" (LLM routing):** OPCIONÁLIS, alapból KIKAPCSOLVA. Csak családi/szórakoztató módban (`mode: extended`). Nehéz kérdésnél Szabi „megpuskázza" a választ egy nagyobb modelltől (alapból Opus 4.8), de a saját Yotengrit-értékrendjén szűri — mindig hozzátesz saját nézőpontot, finoman jelzi a puskázást. Hangkapcsoló: „Szabi, puskázz" / „Szabi, ne puskázz". A demón KI (szuverenitás).
