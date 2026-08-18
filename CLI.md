# CLI commands

## HF download logs

```
hf download jabba77/szabi-chat-logs --repo-type dataset --local-dir ./szabi-logs
```

## A v12 modell kirakása a HF Space-re

> ⚠️ **KÉT lépés kell, és a második NEM hagyható ki.** A Space az **adaptert** tölti
> (`hf-space/app.py` → `ADAPTER_REPO`), tehát a feltöltés önmagában nem vált modellt.
> És a Space forrása a **REPÓ**: a `.github/workflows/deploy-hf-space.yml` minden
> `main`-re pusholt `hf-space/**` változásnál felülírja a Space-t. Egy kézi
> `hf upload spaces/...` csak a következő `main`-pushig él (ezt a #41 tanulta meg).

### 1. Az adapter feltöltése HF-re

A mappa-szerkezet kövesse a v11-ét (`8b/lora/`, `3b/lora/`), mert az `app.py` a
`subfolder`-t adja meg:

```
hf upload jabba77/Szabi-Llama-v12 \
    training/tests/v12/llama3.1-8b-v12/lora-adapter 8b/lora
```

A 3B opcionális (a demó a 8B-t használja, és a 3B fine-tune a v13-ból kimarad):

```
hf upload jabba77/Szabi-Llama-v12 \
    training/tests/v12/llama3.2-3b-v12/lora-adapter 3b/lora
```

Ellenőrzés:

```
hf download jabba77/Szabi-Llama-v12 --include "8b/lora/adapter_config.json" --quiet
```

### 2. A Space átállítása — feature branch + PR, NEM kézi upload

```
git checkout main && git pull
git checkout -b feature/hf-space-v12
```

`hf-space/app.py`-ban egyetlen sor:

```python
ADAPTER_REPO = "jabba77/Szabi-Llama-v12"     # volt: ...-v11
```

```
cd robot && PYTHONPATH=src python3 -m pytest tests/test_hf_space_bundle.py -q && cd ..
git commit -am "hf-space: a Space a v12-es adapterrel fusson"
git push -u origin feature/hf-space-v12
gh pr create --base main --fill
```

Merge után a workflow magától deployol.

### 3. Ellenőrzés, hogy tényleg fut

```
curl -s https://huggingface.co/api/spaces/jabba77/Szabi-Chat | python3 -m json.tool | grep -A2 runtime
```

`runtime.stage` legyen `RUNNING`. A build 2-4 perc; addig `BUILDING`.

### 4. Ha a korpusz is változott

A Space a **becsomagolt** korpuszt tölti, nem építi:

```
PYTHONPATH=robot/src python3 -m freedroid.rag.corpus
cp training/rag/yotengrit_corpus.json hf-space/yotengrit_corpus.json
```

Enélkül a RAG-javítás nem ér el a Space-re (ezt a #47 tanulta meg). A
`test_hf_space_bundle.py` őrzi — ha piros, ez maradt ki.

## Ollama a keor-on (nincs systemd)

```
export OLLAMA_MODELS=/home/csaba/.ollama/models
nohup ollama serve > /tmp/ollama.log 2>&1 &
ollama list
```

## Egy letöltött fine-tune regisztrálása Ollamába

Az Unsloth `Modelfile`-ját **ne** használd (nincs benne SYSTEM, `temperature 1.5`):

```
cd training
python3 make_modelfile.py --variant llama8b \
    tests/v12/llama3.1-8b-v12/gguf-q4_k_m_gguf/Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf
cd tests/v12/llama3.1-8b-v12/gguf-q4_k_m_gguf
ollama create szabi-8b-v12 -f Modelfile_Meta-Llama-3.1-8B-Instruct.Q4_K_M
```

## Mérések

```
python3 training/tech_retrieval_probe.py                      # technikai RAG: 18/20
python3 training/tool_reliability.py --models szabi-8b-v12 --repeat 3
python3 training/rag_citation.py --models szabi-8b-v12 --repeat 10
python3 training/analyze_chat_log.py szabi-logs/data/<log>.jsonl
```

## Tools

scripts/servo_test.py kész (--centre-only, majd --channel pan --range 0.15)


