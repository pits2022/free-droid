# 🦥 Unsloth útmutató — Free-Droid (Szabi) fine-tuning

Ez az útmutató a Free-Droid projekt fine-tuningjához készült. Magyarázza mi az Unsloth, hogyan használod a Colab-bal, és milyen hiperparaméterek kellenek a 615 példás magyar persona-dataset tréningjéhez.

---

## 1. Mi az Unsloth és hogyan viszonyul a Colabhoz?

Két különböző dolog, ne keverd őket:

| | Mi ez | Szerep |
| :--- | :--- | :--- |
| **Google Colab** | Bérelt felhő-számítógép GPU-val (T4 ingyen) | a **vas**, amin a tréning fut |
| **Unsloth** | Python library (kódkönyvtár) | a **szoftver**, ami a vason fut |

**A workflow:**
1. Megnyitsz egy Unsloth Colab notebookot a böngészőben.
2. A notebook első cellája telepíti az Unsloth-ot a Colab gépére (`pip install unsloth`).
3. Lefuttatod a cellákat sorban — a tréning a **Google T4 GPU-ján** zajlik, nem a te gépeden.
4. A végén letöltöd a kész GGUF modellt.

> A te laptopod csak egy böngészőablakot mutat. A számítás a felhőben történik. Nincs mit „elindítani" a saját gépeden.

**Miért Unsloth és nem sima Hugging Face?**
- 2–5× gyorsabb tréning, 60–80% kevesebb VRAM — drop-in csere a HF API-ra.
- Az ingyenes T4-en (16 GB VRAM) kényelmesen elfut egy 3B modell QLoRA tréningje.
- Natív támogatás: Qwen 2.5, Llama 3.2 (a te két A/B jelölted), és export GGUF-ba (Ollama).

---

## 2. A Free-Droid fine-tuning lépésről lépésre

### 2.1 Notebook beszerzése
Az Unsloth kész Colab notebookokat ad. Keress a dokumentációjukban (unsloth.ai/docs) vagy a GitHub-jukon:
- **Qwen 2.5 (3B)** notebook — az A/B teszt 1. jelöltje
- **Llama 3.2 (3B)** notebook — az A/B teszt 2. jelöltje

> A két jelöltet ugyanazzal a notebook-sablonnal tréningeled, csak a `model_name` sor más. Lásd lent.

### 2.2 A telepítő cella
```python
pip install "unsloth[colab-new]" --upgrade
```

### 2.3 Modell betöltése — itt a base modell cseréje (A/B)
```python
from unsloth import FastLanguageModel
import torch

max_seq_length = 2048   # a Free-Droid példák rövidek, ez bőven elég
dtype = None            # auto (T4-en float16)
load_in_4bit = True     # QLoRA — 4-bit base

# A/B TESZT — csak ezt az egy sort cseréled a két modell között:
model_name = "unsloth/Qwen2.5-3B"        # 1. jelölt
# model_name = "unsloth/Llama-3.2-3B"    # 2. jelölt

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = model_name,
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)
```

### 2.4 LoRA adapter hozzáadása
```python
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,                      # LoRA rank — lásd hiperparaméterek
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,             # = r (jó kiindulás)
    lora_dropout = 0,            # 0 = leggyorsabb, Unsloth-optimalizált
    bias = "none",
    use_gradient_checkpointing = "unsloth",  # hosszú kontextushoz, kevesebb VRAM
    random_state = 42,           # reprodukálhatóság
)
```

### 2.5 A Free-Droid dataset betöltése
A `train.jsonl` Alpaca formátumú (instruction / input / output). Töltsd fel a Colabba, vagy húzd be Google Drive-ról.

```python
from datasets import load_dataset

# Alpaca prompt sablon
alpaca_prompt = """Az alábbi egy feladat leírása. Írj választ, amely megfelelően teljesíti a kérést.

### Utasítás:
{}

### Bemenet:
{}

### Válasz:
{}"""

EOS_TOKEN = tokenizer.eos_token   # FONTOS: e nélkül végtelenül generál

def formatting_func(examples):
    texts = []
    for instr, inp, out in zip(examples["instruction"], examples["input"], examples["output"]):
        text = alpaca_prompt.format(instr, inp, out) + EOS_TOKEN
        texts.append(text)
    return {"text": texts}

dataset = load_dataset("json", data_files="train.jsonl", split="train")
dataset = dataset.map(formatting_func, batched=True)
```

### 2.6 Tréning konfiguráció
```python
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,    # effektív batch = 2×4 = 8
        warmup_steps = 5,
        num_train_epochs = 2,               # lásd hiperparaméterek
        learning_rate = 2e-4,
        fp16 = True,                        # T4-en
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 42,
        output_dir = "outputs",
    ),
)

trainer.train()
```

### 2.7 Teszt a tréning után (még Colabban)
```python
FastLanguageModel.for_inference(model)   # 2× gyorsabb inferencia
inputs = tokenizer([alpaca_prompt.format("Ki vagy?", "", "")], return_tensors="pt").to("cuda")
outputs = model.generate(**inputs, max_new_tokens=128)
print(tokenizer.batch_decode(outputs))
```

### 2.8 Export GGUF-ba (Ollama / RPi 5 / CAX31)
```python
# Q4_K_M edge-re (RPi 5) és cloud-ra (CAX31) is jó kiindulás
model.save_pretrained_gguf("freedroid_qwen", tokenizer, quantization_method = "q4_k_m")
# Opcionálisan Q8 a cloud-ra, ha a minőség fontosabb:
# model.save_pretrained_gguf("freedroid_qwen_q8", tokenizer, quantization_method = "q8_0")
```

Letöltöd a `.gguf` fájlt, és Ollama Modelfile-lal betöltöd mindkét rétegen (ugyanaz az ARM GGUF megy az RPi 5-re és a CAX31-re).

---

## 3. Hiperparaméterek — mit állíts és miért

A Free-Droid feladat: **persona/stílus** tanítás 615 magyar példán. Ez NEM tudás-tanítás, ami fontos a beállításoknál.

| Paraméter | Érték | Miért |
| :--- | :--- | :--- |
| `r` (LoRA rank) | **16** | A „kapacitás". 8 = alultanul a personán, 32 = nem ad többet, csak lassít. 16 a bevált arany középút stílushoz. |
| `lora_alpha` | **16** | A LoRA súlyozása. Jó kiindulás: = `r`. (Néha 2×r-t használnak, de itt az 1:1 stabil.) |
| `lora_dropout` | **0** | Unsloth ezzel a leggyorsabb. Kis dataseten nincs szükség dropout-regularizációra. |
| `num_train_epochs` | **2** | KRITIKUS. 615 példán 2 epoch elég. 3+ → overfitting (robotikus, ismétlő válaszok). Ha a persona gyenge, előbb a datasetet bővítsd, ne az epochot emeld. |
| `learning_rate` | **2e-4** | A LoRA standard kiindulása. Túl magas → instabil; túl alacsony → nem tanul. 2e-4 jól bevált. |
| `max_seq_length` | **2048** | A Free-Droid példák rövidek (átlag ~200 karakter). 2048 bőven fedi, és gyors. |
| `per_device_train_batch_size` | **2** | T4 VRAM-ba belefér 3B-nél. |
| `gradient_accumulation_steps` | **4** | Effektív batch = 2×4 = 8. Stabilabb gradiens kis VRAM mellett. |
| `weight_decay` | **0.01** | Enyhe regularizáció overfitting ellen. |
| `optim` | **adamw_8bit** | Memóriatakarékos optimizer, T4-re ideális. |
| `seed` / `random_state` | **42** | Reprodukálhatóság — fontos az A/B teszthez, hogy fair legyen. |

> ⚠️ **A/B teszt fairness:** mindkét modellnél (Qwen, Llama) PONTOSAN ezek a paraméterek legyenek. Csak a `model_name` változik. Különben nem a modellt hasonlítod, hanem a beállításokat.

---

## 4. Az overfitting felismerése — a legfontosabb veszély

615 példa kevés, könnyű túltanítani. Tünetek:
- A modell **szó szerint visszaadja** a dataset példáit, de új kérdésre esetlen.
- **Ismétlő, robotikus** válaszok, mindig ugyanaz a fordulat.
- A **training loss nagyon alacsony** (pl. 0.2 alatt), de a **validation loss nő**.

**Ellenszer:**
1. Figyeld a `val.jsonl`-en a validation loss-t (állíts be `eval_steps`-et).
2. Ha a train loss esik, de a val loss nő → **csökkentsd az epochot** (2 → 1).
3. Ne a loss-t hajszold, hanem a `persona_benchmark.json` valós kérdésein nézd a minőséget.

> Empirikus tapasztalat: egy 0.28 train loss-os, „túlcsiszolt" modell rosszabb élő válaszokat ad, mint egy 0.52-es, ami 2 epochnál állt meg.

---

## 5. Tipikus hibák (amibe bele szoktak futni)

1. **Hiányzó EOS token** → a modell végtelenül generál. Mindig fűzd hozzá az `EOS_TOKEN`-t a formázásnál (lásd 2.5).
2. **Colab szétkapcsol** → az ingyenes T4 ~3-4 óra után leválhat. A te tréninged (~30-50 perc) bőven belefér, de ments gyakran.
3. **Base vs Instruct modell keverése** → a persona fine-tuninghoz a **base** modell jó kiindulás (`Qwen2.5-3B`, nem `Qwen2.5-3B-Instruct`), mert te adod neki a personát. (Ha az Instruct jobban tartja a magyar nyelvet, az A/B tesztben kiderül — érdemes mindkettőt megnézni.)
4. **A GGUF nem tölt be Ollamába** → ellenőrizd hogy a Modelfile a helyes kvantálású fájlra mutat, és hogy ARM buildet használsz az RPi 5 / CAX31-en.
5. **Eltérő paraméterek az A/B-ben** → érvénytelen összehasonlítás. Fixáld a seedet és minden hiperparamétert.

---

## 6. A teljes folyamat egy mondatban

Megnyitsz egy Unsloth Colab notebookot → telepít → betöltöd a Qwen 2.5 3B-t (vagy Llama 3.2 3B-t) → ráteszed a LoRA-t (r=16) → betöltöd a `train.jsonl`-t → `trainer.train()` (2 epoch, ~30-50 perc) → teszteled → exportálod GGUF Q4_K_M-be → letöltöd → Ollamába töltöd az RPi 5-ön és a CAX31-en.

Aztán ugyanezt a másik modellel, és a `persona_benchmark.json` + `ertekelo_sablon.md` alapján eldöntöd, melyik lesz Szabi.
