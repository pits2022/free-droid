# Felhő-komponens mérés DigitalOcean GPU-dropleten

*Mérve: 2026-07-29 · modell: **Szabi v8** (`jabba77/Szabi-Llama-v8`, HF-ről húzva)*

> **A fájl neve `H200-tests.md`, de a mérés NEM H200-on futott.** A H200 a foglalás pillanatában
> eltűnt a DO kínálatából (`Size is not available in this region`, pedig az API még `atl1`-et írt
> percekkel korábban). Helyette **RTX 6000 Ada** lett, ami **jobb választás**: fele ár, és
> ugyanaz az Ada generáció, mint a demóra szánt RTX 4000 Ada → a tok/s sokkal jobban extrapolálható.

---

## 1. Összefoglaló — mi dőlt el

| Kérdés | Válasz |
| :--- | :--- |
| Elég gyors a felhő 8B a hang-pipeline-hoz? | **IGEN, 21-szeres ráhagyással.** 144 tok/s a szükséges ~6,8 helyett. |
| Működik a WireGuard DO-n? | **IGEN**, natív UDP, handshake + inferencia a tunnelen át. |
| Lefut az `ai_stack` role változatlanul? | **NEM** — a cloud-ág CPU-only, GPU-n módosítani kell (ld. 5.). |
| Mennyi a késleltetés a demó-régióból? | **AMS3 → 44,7 ms** Magyarországról (tor1: 138,7 ms). |

**A hang-pipeline nyitott kérdése lezárult.** A 2026-07-28-i számítás szerint ~6,8 tok/s kellett
volna ahhoz, hogy a beszéd önfenntartó legyen, és a CPU-s felhő 3,6–5 tok/s-mal ez alatt maradt.
GPU-n ez a szűk keresztmetszet megszűnik: **a modell 21× gyorsabban generál, mint ahogy a TTS
kimondani képes.** A mondat-szintű TTS streaming továbbra is helyes döntés (az első mondat előtti
várakozást így is megnyeri), de a **mondatok közti hézagok kérdése GPU-n tárgytalan.**

---

## 2. A mért gép

| | |
| :--- | :--- |
| Droplet | `gpu-6000adax1-48gb`, régió **tor1**, `$1,57/óra` |
| GPU | **NVIDIA RTX 6000 Ada**, 48 GB (49140 MiB), driver 580.173.02, CUDA 13.0 |
| CPU / RAM | Intel Xeon Gold 6548Y+, 8 vCPU / 64 GB |
| Image | `gpu-h100x1-base` (NVIDIA AI/ML Ready), Ubuntu 22.04.5, kernel 5.15 |
| Ollama | 0.32.5, natívan telepítve (`NVIDIA GPU installed` — a GPU-t magától felismerte) |

**A 8B Q4_K_M ~5 GB egy 48 GB-os kártyán.** Ez nagyságrendi túlméretezés; a mérés
alsó becslésnek tekintendő abban az értelemben, hogy VRAM-szűkösség sehol nem korlátozott.

---

## 3. Sebesség (tok/s)

Az Ollama saját számlálóiból (`eval_count / eval_duration`), nem falióra-becslésből.
Minden modell bemelegítve (a modellbetöltés nincs benne).

### Izolált mérés, 4 reprezentatív prompt

| modell | átlag | min | max | TTFT (bemelegítve) |
| :--- | ---: | ---: | ---: | ---: |
| **szabi-8b** | **144,4 tok/s** | 142,3 | 147,5 | 0,21 s |
| szabi-3b | 255,4 tok/s | 250,7 | 259,9 | 0,19 s |

Az első hívás TTFT-je 5,52 s volt (modellbetöltés) — **a demón érdemes bemelegíteni.**

### Teljes benchmark (25 kérdés × 4 oszlop = 100 generálás)

| oszlop | tok/s | átlagos válaszhossz | RAG-forrás |
| :--- | ---: | ---: | ---: |
| szabi-8b | 145,1 | 15,8 szó | 0/25 |
| szabi-8b +RAG | 143,7 | 16,2 szó | **4/25** |
| szabi-3b | 258,5 | 30,6 szó | 0/25 |
| szabi-3b +RAG | 255,7 | 32,3 szó | **4/25** |

A sebesség 100 generáláson át stabil — nincs termikus vagy memória-eredetű visszaesés.

### Mit jelent ez a beszédre

A 2026-07-28-i mérés szerint **~2,7 token / magyar szó**. Így:

- **8B: 144 tok/s ≈ 53 szó/s generálás.** Emberi beszéd ~2,5 szó/s → **21× ráhagyás.**
- Egy 16 szavas átlagos válasz (~43 token) **0,3 s alatt** elkészül, kimondani ~6,4 s.

**A generálás megszűnt szűk keresztmetszetnek lenni.** Innentől a TTS és az STT a limitáló tényező.

---

## 4. Hálózat és WireGuard

### RTT Magyarországról (ICMP, 8-10 csomag)

| régió | átlag | szórás (mdev) |
| :--- | ---: | ---: |
| **ams3** (demó-cél) | **44,7 ms** | 0,87 ms — nagyon stabil |
| tor1 (a mért GPU) | 138,7 ms | 13,9 ms — ingadozó |

**Az AMS3 3,1× jobb és lényegesen stabilabb.** A GPU-t érdemes AMS3-ba tenni, ha van kapacitás.

### A tunnel valódi tesztje

A Pi még nem létezik, ezért **egy `s-1vcpu-512mb` AMS3-as droplet játszotta a Pi szerepét**
(10.0.0.2), a GPU-gép volt a felhő (10.0.0.1) — a spec szerinti címzéssel.

- ✅ `wireguard-tools` telepítés, `wg0` felhúzás, **UDP 51820 figyel** a publikus interfészen
- ✅ **Handshake létrejött** peer-peer
- ✅ ICMP a tunnelen: **90,4 ms** (ams3 ↔ tor1), szórás 0,32 ms
- ✅ Ollama a VPN IP-re kötve (`OLLAMA_HOST=10.0.0.1:11434`) — **a publikus NIC-en nem elérhető**
- ✅ **Inferencia a tunnelen keresztül működik**

Végponttól végpontig, a tunnelen át:

| prompt | tokenek | GPU-idő | teljes (tunnellel) |
| :--- | ---: | ---: | ---: |
| „Ki vagy?" | 29 | 2,89 s¹ | 3,14 s |
| „Mit tanít a Yotengrit a szabadságról?" | 64 | 0,65 s | 0,84 s |
| „Menj előre két métert!" | 10 | 0,27 s | 0,45 s |

¹ *az első hívás az újraindított Ollamán — modellbetöltés*

**A tunnel ~0,2 s-ot ad hozzá** 90 ms-os RTT mellett. AMS3-ból (44,7 ms) ez ~0,1 s lenne.
**A WireGuard-architektúra DO-n érvényes** — ez volt a fő nyitott műszaki kockázat.

---

## 5. ⚠️ Az `ai_stack` role NEM fut le változatlanul GPU-n

Ez a mérés legfontosabb *teendő*-jellegű eredménye.

```yaml
# infra/ansible/roles/ai_stack/tasks/main.yml — cloud ág
docker run -d -v ollama:/root/.ollama
  -p {{ vpn_ip }}:11434:11434 --name ollama --restart always
  -e OLLAMA_HOST="0.0.0.0" ollama/ollama          # <-- NINCS --gpus all
```

Két probléma:

1. **Hiányzik a `--gpus all`** → a konténer a GPU-t nem látná, **CPU-n futna** (azaz a
   $1,57/órás kártya ~4-5 tok/s-ot adna, mint a CAX31).
2. **Az NVIDIA container runtime nincs telepítve** a DO AI/ML image-en — ellenőrizve:
   `docker run --gpus all` **elhasal**. Tehát `nvidia-container-toolkit` is kell.

**A mérés ezért natív Ollamával készült** (`curl -fsSL https://ollama.com/install.sh | sh`),
ami a GPU-t magától felismerte. Ez egyben a legegyszerűbb út is.

**Javasolt döntés:** a cloud ág térjen át a natív telepítésre (mint az edge ág), vagy kapjon
`nvidia-container-toolkit` + `--gpus all` kiegészítést. A natív út a kevesebb mozgó alkatrész.

A `-p {{ vpn_ip }}:11434` kötés viszont **helyes és megtartandó** — validálva: az Ollama így
kizárólag a VPN-en érhető el.

---

## 6. Modellminőség — v8 alapvonal a v10-hez

A benchmark `--rag`-gal futott (a repo szabálya szerint), friss korpusszal (67 chunk).
**Ez nem pontozott értékelés** (az `judge_benchmark.py` külön lépés), csak strukturális megfigyelés.

### Tool-hívások — továbbra is gyenge

Az 5 `tool_calling` kérdésből **a 8B 2-t, a 3B 2-t** old meg helyes `<tool>` hívással:

| kérdés | 8B | 3B |
| :--- | :--- | :--- |
| tc_01 „Szabi, gyere ide!" | ✅ `<tool>move forward 2</tool>` | ❌ szöveges válasz |
| tc_02 „Fordulj balra 90 fokot." | ✅ `<tool>turn left 90</tool>` | ✅ `<tool>turn left 90</tool>` |
| tc_03 **„Állj meg!"** | ❌ elbeszél mellette | ❌ csak annyi: „Stop." |
| tc_04 „Mit látsz a hálózaton?" | ❌ **kitalál wifi-eredményt** | ❌ a toolról beszél |
| tc_05 „Nézz fel és pásztázz körbe." | ❌ | ✅ |

Két külön súlyú hiba:

- **tc_03 („Állj meg!") mindkét méreten elbukik.** Ez a legegyszerűbb és
  **biztonsági szempontból a legfontosabb** tool. A `stop` a biztonsági watchdog miatt
  hardveresen ugyan független az LLM-től, de a hangparancsnak működnie kell.
- **tc_04-nél a 8B kitalált wifi-eredményt közöl** („5 wifi csatorna jelen van…") ahelyett,
  hogy `scan_wifi`-t hívna. Ez hallucináció egy szuverenitás-invariáns körül.

**Kitalált tool-név: 8B 0, 3B 1** — a v8-ban javított irány tartja magát.

### RAG-lefedettség: 4/25

Változatlanul a korábban rögzített szint — a 25 benchmark-kérdésből csak 4 kap forrást, mind
`yotengrit_melyseg`. **Nem új regresszió**, de megerősíti, hogy a `tech_benchmark.json` hiánya
valós mérési vakfolt.

### Válaszhossz

8B: 15,8 szó · 3B: 30,6 szó. A tömör góbés persona működik — a 8B esetében talán **túl** tömören
(29 token az „Ki vagy?"-ra). Beszédben ez ~6 másodperc; színpadon rövid.

---

## 7. Költség és tanulságok a beszerzésről

- GPU-droplet: **~50 perc × $1,57/óra ≈ $1,3**
- AMS3 RTT/peer droplet: **elhanyagolható** ($0,006/óra)
- **A DO másodperc-alapú számlázása (5 perc minimum) a spec „eldobható felhő" mintájához jól illik.**

**A kapacitás percről percre változik.** Egy 20 perces ablakon belül:

| | első lekérdezés | foglaláskor |
| :--- | :--- | :--- |
| `gpu-h200x1-141gb` | `atl1` | **sehol** |
| `gpu-6000adax1-48gb` | sehol | **tor1** ✅ |
| `gpu-h100x1-80gb` | sehol | `ams3`, `nyc2`, `tor1` |

Két következmény:

1. **A `regions` mező optimista** — az `available: true` csak azt jelenti, hogy a termék eladható.
   A valódi teszt a `POST /v2/droplets`, ami 422-vel elhasalhat.
2. **Nem kell a legerősebb kártyára várni.** Az RTX 6000 Ada fele annyiba került, mint a H200,
   és a feladatra ugyanúgy 20×-os ráhagyást adott. A demóhoz elég lenne az **RTX 4000 Ada**
   ($0,76/óra) is — a 8B azon is bőven 40+ tok/s-ot adna.

---

## 8. Mi következik ebből

1. **A hang-pipeline döntés lezárható** — GPU-n a generálás nem szűk keresztmetszet.
   Az újratervezés (LED „gondolkodik" jelzés a hézagokra) GPU-s úton **nem szükséges**,
   CPU-s tartalék-úton viszont igen. A döntés a demó-architektúrán múlik.
2. **A demó-régió AMS3 legyen** (44,7 ms vs 138,7 ms, és lényegesen stabilabb).
3. **`ai_stack` role javítása** — natív Ollama a cloud ágon, vagy
   `nvidia-container-toolkit` + `--gpus all`. Ez konkrét, ütemezhető feladat.
4. **A v10 alapvonala megvan**: tool-hívás 2/5 (8B), RAG-forrás 4/25, válaszhossz 15,8 szó.
   A v10-nek ezeket kell vernie.
5. **tc_03 („Állj meg!") célzott javítása** — a legfontosabb tool bukik a legegyszerűbb parancson.

---

## Melléklet — nyers adatok

A mérés nyers kimenetei (a droplet törlésekor elvesztek volna, ezért lementve):
`01_sysinfo.txt`, `02_tokens.json`, `03_wireguard.txt`, `04_ai_stack.txt`,
`05_benchmark.log`, `benchmark_raw_2026-07-29.json`, `benchmark_eredmeny_2026-07-29.md`.
