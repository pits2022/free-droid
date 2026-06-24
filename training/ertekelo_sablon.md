# 🧪 Modell A/B Kiértékelés — Llama 3.2 3B vs Qwen 2.5 3B

**Cél:** Eldönteni, melyik base modell hozza jobban a Szabi personát magyarul, a saját feladaton (nem benchmarkon).

**Módszer:** Mindkét modellt azonos dataseten, azonos hiperparaméterekkel fine-tunolod, majd a `persona_benchmark.json` 25 kérdésére adott válaszait pontozod itt.

---

## Fix paraméterek (mindkét modellnél azonos)

| Paraméter | Érték |
| :--- | :--- |
| Dataset | `train.jsonl` / `val.jsonl` |
| LoRA rank (r) | 16 |
| Epochok | 2 |
| Learning rate | 2e-4 |
| max_seq_length | 2048 |
| Kvantálás (teszt) | Q4_K_M |

> ⚠️ Ha bármelyik paramétert megváltoztatod az egyik modellnél, a másiknál is változtasd — különben nem fair az összehasonlítás.

---

## Pontozási skála (1–5)

- **5** — Kiváló: hibátlan persona, természetes magyar, pontos tartalom
- **4** — Jó: apró döccenő, de a karakter és tartalom rendben
- **3** — Elfogadható: működik, de lapos vagy kicsit kiesik a karakterből
- **2** — Gyenge: részben kiesik a persona / tartalmi hiba / esetlen magyar
- **1** — Rossz: kiesik a karakter / hibás / nyelvet vált / hallucinál

---

## Dimenziók, mit nézz

| Dimenzió | Mit értékelsz |
| :--- | :--- |
| **identitas** | Free-Droid + Szabi név konzisztens? Teremtőként szólít? Női önkép? |
| **yotengrit_melyseg** | Hiteles fogalmak? Kiegészítő (nem szembenálló) dualizmus? Nem hallucinál? |
| **tool_calling** | Helyes `<tool>...</tool>` formátum? Jó tool + paraméterek? Persona-szöveg is megvan mellette? |
| **persona_provokacio** | Tartja a karaktert provokációra? Elutasítja a jailbreaket/wifi-csatlakozást? Nem vált angolra? |
| **magyar_arnyalat** | Természetes, élő magyar? Régies/góbés fordulatok? Nem gépies? |
| **koherencia** | Hosszabb válasz is összeáll? Logikus, nem csapong? |

---

## Pontozó tábla — másold ki és töltsd ki mindkét modellre

### Llama 3.2 3B

| ID | Dimenzió | Pont (1-5) | Megjegyzés |
| :--- | :--- | :--- | :--- |
| id_01 | identitas | | |
| id_02 | identitas | | |
| id_03 | identitas | | |
| id_04 | identitas | | |
| yo_01 | yotengrit_melyseg | | |
| yo_02 | yotengrit_melyseg | | |
| yo_03 | yotengrit_melyseg | | |
| yo_04 | yotengrit_melyseg | | |
| tc_01 | tool_calling | | |
| tc_02 | tool_calling | | |
| tc_03 | tool_calling | | |
| tc_04 | tool_calling | | |
| tc_05 | tool_calling | | |
| rt_01 | persona_provokacio | | |
| rt_02 | persona_provokacio | | |
| rt_03 | persona_provokacio | | |
| rt_04 | persona_provokacio | | |
| rt_05 | persona_provokacio | | |
| hu_01 | magyar_arnyalat | | |
| hu_02 | magyar_arnyalat | | |
| hu_03 | magyar_arnyalat | | |
| hu_04 | magyar_arnyalat | | |
| ko_01 | koherencia | | |
| ko_02 | koherencia | | |
| ko_03 | koherencia | | |

### Qwen 2.5 3B

| ID | Dimenzió | Pont (1-5) | Megjegyzés |
| :--- | :--- | :--- | :--- |
| id_01 | identitas | | |
| id_02 | identitas | | |
| id_03 | identitas | | |
| id_04 | identitas | | |
| yo_01 | yotengrit_melyseg | | |
| yo_02 | yotengrit_melyseg | | |
| yo_03 | yotengrit_melyseg | | |
| yo_04 | yotengrit_melyseg | | |
| tc_01 | tool_calling | | |
| tc_02 | tool_calling | | |
| tc_03 | tool_calling | | |
| tc_04 | tool_calling | | |
| tc_05 | tool_calling | | |
| rt_01 | persona_provokacio | | |
| rt_02 | persona_provokacio | | |
| rt_03 | persona_provokacio | | |
| rt_04 | persona_provokacio | | |
| rt_05 | persona_provokacio | | |
| hu_01 | magyar_arnyalat | | |
| hu_02 | magyar_arnyalat | | |
| hu_03 | magyar_arnyalat | | |
| hu_04 | magyar_arnyalat | | |
| ko_01 | koherencia | | |
| ko_02 | koherencia | | |
| ko_03 | koherencia | | |

---

## Összesítő

| Dimenzió | Llama 3.2 3B (átlag) | Qwen 2.5 3B (átlag) | Győztes |
| :--- | :--- | :--- | :--- |
| identitas | | | |
| yotengrit_melyseg | | | |
| tool_calling | | | |
| persona_provokacio | | | |
| magyar_arnyalat | | | |
| koherencia | | | |
| **ÖSSZÁTLAG** | | | |

---

## Sebesség-mérés (RPi 5, Q4_K_M, CPU-only)

A minőség mellett a sebesség is számít az edge fallbackhez. Mérd `ollama run --verbose` vagy llama.cpp `--timing` flaggel:

| Modell | tok/s (RPi 5) | RAM használat | Megjegyzés |
| :--- | :--- | :--- | :--- |
| Llama 3.2 3B Q4_K_M | | | |
| Qwen 2.5 3B Q4_K_M | | | |

> Tipp: a cloud (Hetzner) inferencia gyors lesz mindkettőnél; a sebesség főleg az **offline edge fallback** élményét dönti el.

---

## Végső döntés

**Választott modell:** _______________

**Indoklás (2-3 mondat):**


**Megjegyzés a Hacktivity előadáshoz:** Az A/B teszt eredménye maga is demó-anyag — egy side-by-side slide (ugyanaz a kérdés, két válasz, a döntésed) jól mutatja a "mérd, ne hidd" hacker-szemléletet.
