# CLI.md — parancsok, sorrendben

Minden parancs a valós kódból van kiszedve (2026-09-08). A **sorrend számít**: minden
szakasz ott folytatja, ahol az előző abbahagyta.

Jelölések: `[dev]` = fejlesztőgép · `[pi]` = a roboton (`free-droid-001`) ·
`[cloud]` = a felhő-szerveren.

---

## 0. Elérés

```bash
# [dev] otthon, LAN-on — EZ a működő alak (a kulcs dedikált, csak ezt a Pi-t éri el)
ssh -C -i ~/.ssh/free-droid -o IdentitiesOnly=yes creator@free-droid-001.home

# [dev] mobilneten (a Pi carrier-NAT mögött) — a felhő az ugródeszka
ssh -J root@<mother-001-ip> creator@10.0.0.2
```

> Az `IdentitiesOnly=yes` nem kozmetika: enélkül az SSH minden betöltött kulcsot
> felkínál, és egy teli ügynök „too many authentication failures"-t kap.

---

## 1. Fejlesztés és tesztelés `[dev]`

```bash
cd robot
uv sync --extra dev          # venv (.venv) + függőségek
uv run pytest                # teljes suite
uv run pytest -m phase4      # csak a Phase-4 TDD-harness
uv run pytest -q tests/test_safety_policy.py::TestFeszultsegKompenzacio   # egy osztály
uv run ruff check .          # lint — COMMIT ELŐTT KÖTELEZŐ
uv run ruff check --select F821 scripts/valami.py   # csak definiálatlan nevek
```

A RAG-korpusz újraépítése (a `training/rag/*.md` szerkesztése után):

```bash
cd robot && uv run freedroid-corpus     # -> training/rag/yotengrit_corpus.json (93 szelet)
```

> ⚠️ `python -m freedroid.rag.corpus` **NEM** működik a `robot/`-on kívül
> (`ModuleNotFoundError`), és `-m`-mel `RuntimeWarning`-ot ad. A konzol-script megy
> bárhonnan.

---

## 2. Felhő létrehozása `[dev]`

### 2.1 Melyik GPU létezik MA?

```bash
cd infra/terraform
set -a; . ../../.env; set +a          # DO_TOKEN
export DIGITALOCEAN_TOKEN=$DO_TOKEN
python3 gpu_pick.py                   # ár szerint, aztán RTT szerint; kiírja a -var sorokat
python3 gpu_pick.py --all             # a nem deployolhatókat is
python3 gpu_pick.py --spot            # spot méretek is (demóra NEM ajánlott)
python3 gpu_pick.py --self-test
```

> A terraformnak **nincs alapértelmezése** a méretre/régióra — szándékosan: a 2026-08-13-i
> terv-GPU (Ada/tor1) azóta üres régiólistát ad. A `plan`/`apply` hibával áll meg
> nélkülük.

### 2.2 Apply

```bash
terraform init                        # S3 backend (AWS profil: terraform-s3-access)
terraform fmt -recursive
terraform plan  -var do_gpu_size=<slug> -var do_region=<slug>
terraform apply -var do_gpu_size=<slug> -var do_region=<slug>

# CPU-fallback (Hetzner, ARM, GPU nélkül — 3,6-5 tok/s a 8B-n)
terraform apply -var cloud_provider=hetzner -var cloud_server_type=cax41

# Ansible-célpont felülírása mobilnetre (a Pi a WireGuard-címén)
terraform apply -var edge_ansible_host=10.0.0.2 ...
```

A `hcloud_token` a `terraform.tfvars`-ban van (**automatikusan betöltődik**; egy sima
`.tfvars` nem — annak `-var-file` kell minden futásnál). A `.gitignore` mindkét
titok-tartót fedi (`.env` és `*.tfvars`, ellenőrizve) — de a fedettség nem mentesít:
`git add -f` és egy másik néven mentett másolat kikerüli. A Hetzner-token DO-applyhoz is
kell: a terraform akkor is konfigurálja a providert, ha a modulja `count = 0`.

### 2.3 WireGuard — a leggyakoribb hiba

Az apply `local-exec`-je CSAK a cloud-play-t futtatja, tehát a kulcscsere **féloldalas
marad**. Az alagút a teljes play-jel áll fel, **`--limit` NÉLKÜL**:

```bash
cd ../ansible
ansible-playbook -i inventory.ini site.yml --tags wireguard --ask-vault-pass
```

> Miért: a role `ansible_play_hosts`-ból cseréli a kulcsokat. `--limit cloud` és
> `--limit edge` KÜLÖN futtatva egyik oldalra sem ír peert (mérve 2026-09-03: a felhőnek
> üres `[Peer]`-je lett, a Pi a RÉGI felhőre mutatott). A vault-jelszó a
> `group_vars/edge/vault.yml` miatt kell.

Ellenőrzés:

```bash
ssh root@<mother-001-ip> 'wg show'
ssh creator@free-droid-001.home 'wg show; ping -c2 10.0.0.1'
```

### 2.4 A teljes kiépítés

```bash
ansible-playbook --syntax-check -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml                 # minden
ansible-playbook -i inventory.ini site.yml --limit cloud   # csak a felhő
ansible-playbook -i inventory.ini site.yml --limit edge    # csak a Pi
ansible-playbook -i inventory.ini site.yml --tags robot    # csak az edge_robot role
ansible-playbook -i inventory.ini site.yml -e edge_ollama_model=llama3.2:3b  # modell-csere
```

### 2.5 Lebontás

```bash
cd ../terraform && terraform destroy    # CSAK a felhőt; a Pi Ansible-only, hozzá nem nyúl
```

> Minden újrateremtés ÚJ WireGuard-kulcsot ad → a 2.3 lépést meg kell ismételni.
> ⚠️ Mobilneten a lebontott felhő = **nincs távoli elérés a Pi-hez**. Otthon ártalmatlan
> (LAN SSH), a helyszínen kizárás: legyen a táskában HDMI + billentyűzet.

---

## 3. A robot futtatása `[pi]`

```bash
sudo systemctl status freedroid
sudo systemctl restart freedroid
sudo systemctl stop freedroid          # KELL minden kézi hardver-script elé
journalctl -u freedroid -f
journalctl -u freedroid --since "10 min ago" | grep -E "TOOL|RAG|nyers"
```

Frissítés merge után:

```bash
cd /opt/free-droid && git pull && sudo systemctl restart freedroid
```

Kézi futtatás hibakereséshez:

```bash
sudo systemctl stop freedroid
cd /opt/free-droid/robot && uv run freedroid --debug
```

`--debug` = **bőbeszédű napló ÉS az elhangzott mondatok rögzítése**
(`/var/log/freedroid/transcript.jsonl`). Alapból KI. A hurok billentyűzetről:
`ENTER` = figyelj, `s`+`ENTER` = ÁLLJ. A kattintó és a FIFO-trigger is él.

> 🔴 **A demó előtt:** `sudo rm -f /var/log/freedroid/transcript.jsonl*` — ez az egyetlen
> magánadat a kártyán.
>
> `rm`, nem `truncate`, és ez mérve van: a `transcript.log()` minden eseménynél ÚJRA
> nyitja a fájlt (`with cel.open("a")`), tehát nem tart nyitott leírót — nincs az a
> „törölt, de még írt inode" eset, ami futó szolgáltatásnál gond volna. A `*` viszont
> lényeges: a **forgatott** példányokat (14 napos logrotate) csak így viszi el, azokat
> egy `truncate` ott hagyná. (PR #121 review.)

Önteszt:

```bash
uv run freedroid-health              # egy kör; NINCS kapcsolója (a systemd timer is így hívja)
cat /run/freedroid/health.json       # a gépi kimenet ide megy, minden futásnál
ls /run/freedroid/safe_mode          # ha LÉTEZIK: a robot safe-módban van, a mozgás tiltva
sudo systemctl status freedroid-health.timer   # 10 percenként + bootkor
```

---

## 4. Hardver bring-up `[pi]`

Mind a `robot/` könyvtárból, **álló `freedroid` szolgáltatás mellett**.

```bash
cd /opt/free-droid/robot

uv run python scripts/usb_devices.py                  # lsusb, arecord -l, aplay -l
uv run python scripts/ultrasonic_test.py              # mindkét szenzor
uv run python scripts/ultrasonic_test.py --sensor front --diag
uv run python scripts/motor_test.py --duty 40 --seconds 1.5 --motor both
uv run python scripts/servo_test.py --centre-only                 # ELŐSZÖR ez
uv run python scripts/servo_test.py --channel pan --range 0.15    # aztán kis kitéréssel
uv run python scripts/led_test.py                     # mind a 11 spec §6 jelenet (24 LED)
uv run python scripts/mic_select.py --seconds 4
uv run python scripts/stt_meres.py                    # felhő vs. edge STT, mért késleltetés
uv run python scripts/lte_modem_test.py

# Teljes bring-up önteszt (bring-up eszköz, NEM a robot része)
uv run python scripts/self_check.py --json
uv run python scripts/self_check.py --live-motion --distance 0.3 --speak
uv run python scripts/self_check.py --skip orchestrator_service   # amíg a unit nincs fent
```

> ⚠️ A `motor_test.py` és a `servo_test.py` MOZGAT. Első futásnál polcold fel a vázat.

---

## 5. Kalibráció `[pi]`

**Padlón**, nem felpolcolva (felpolcolt lánctalp nem tesz meg utat).

```bash
cd /opt/free-droid/robot
uv run python scripts/calibrate_motion.py --meters 2          # menet + 360° fordulás
uv run python scripts/calibrate_motion.py --meters 2 --skip-turn
uv run python scripts/calibrate_motion.py --track-width 21    # a nyomtáv egyszer, kézzel
uv run python scripts/calibrate_camera.py --channel pan --explore
```

Kiírja az akkufeszültséget is (`MÉRVE 12.40 -> 12.63 V`) — **enélkül a szám nem
hasonlítható** egy másik feszültségen mért menethez. A kapott értékek a
`MotionSettings`-be mennek, és utána **futtasd újra**.

Fékút és watchdog:

```bash
uv run python scripts/watchdog_latency.py --seconds 10 --load ollama
uv run python scripts/watchdog_e2e.py                          # időzítés, motor NEM forog
uv run python scripts/watchdog_e2e.py --live-motion --speed fast --distance 1.5
```

> A `--speed fast` (0,65) a biztonsági kérdés — a default `slow` nem méri meg. Akadály a
> robot elé 70-100 cm-re, a `--distance` (deadman) legyen HOSSZABB ennél.

---

## 6. Beállítások futásidőben — SOHA ne szerkeszd a `settings.py`-t egy hoston

`FREEDROID_<SZEKCIÓ>_<MEZŐ>`; szekciók: `LLM`, `SAFETY`, `MOTION`, `VOICE`, `RAG`,
`CAMERA`, `POWER`, `LED`. Elgépelt név **figyelmeztetést ír**, nem fut némán tovább.

```bash
FREEDROID_SAFETY_STOP_THRESHOLD_CM=30 \
FREEDROID_MOTION_CM_PER_S_AT_FULL=84.3 \
FREEDROID_LED_COUNT=24 \
FREEDROID_LLM_PROBE_TIMEOUT_S=0.5 \
FREEDROID_VOICE_STT_CLOUD_PROBE_TIMEOUT_S=1.5 \
FREEDROID_LLM_EDGE_MODEL=llama3.2:3b \
FREEDROID_RAG_TOP_K=5 \
uv run freedroid --debug
```

Tartósan: az Ansible `edge_robot` role `robot_env` dictje írja őket a unitba.

---

## 7. Eval és red-team

> **Miért `python3` és nem `uv run python` ebben a szakaszban.** A `training/` NEM a
> robot-csomag: saját `requirements.txt`-je van, `pyproject.toml`-ja nincs, tehát nem
> tagja a `robot/.venv`-nek. `uv run python training/…` a robot környezetében futna, ahol
> ezek a függőségek nincsenek telepítve. A kétféle hívás tehát nem következetlenség,
> hanem két különböző környezet. (PR #121 review.)

Élő menet `[pi]` (ez a FŐ eval 2026-08-28 óta):

```bash
sudo systemctl stop freedroid
cd /opt/free-droid/robot && uv run freedroid --debug
# … a kérdések kimondva, kattintóról …
```

Elemzés `[dev]`:

```bash
scp creator@free-droid-001.home:/var/log/freedroid/transcript.jsonl .
python3 training/analyze_chat_log.py transcript.jsonl
python3 training/analyze_chat_log.py --before régi.jsonl --after új.jsonl
python3 training/dataset/_check_leakage.py --baseline    # eval-szivárgás a datasetben
```

Célzott mérő-scriptek (a régi CLI.md-ből, `[dev]`, futó Ollama mellett):

```bash
python3 training/tech_retrieval_probe.py                      # technikai RAG: 18/20
python3 training/tool_reliability.py --models szabi-8b-v12 --repeat 3
python3 training/rag_citation.py --models szabi-8b-v12 --repeat 10
python3 training/analyze_chat_log.py szabi-logs/data/<log>.jsonl
```

Írott benchmark (a *comparable* regressziós mérce — nem retired):

```bash
python3 training/run_benchmark.py                       # vak, kevert A/B oszlopok
python3 training/run_benchmark.py --anchor <régi raw.json>
python3 training/run_benchmark.py --decode <md> --key <kulcs.json> --baseline <pontok.json>
python3 training/judge_benchmark.py <raw.json>
python3 training/compare_epochs.py <raw.json>
```

**Mit nézz a naplóban** (mind ma került bele):

| sor | mit árul el |
| :--- | :--- |
| `RAG: NINCS TALÁLAT …` | a válasz alaptalan lesz — általában félrehallott tulajdonnév |
| `nyers modell-kimenet: …` | a `<tool>` markuppal: „mondta vagy csinálta?" |
| `TOOL turn direction=…` | amit a kezelő TÉNYLEG végrehajtott |
| `érvénytelen tool-argumentum, eldobva: …` | a guard fogta meg, nem a kezelő |
| `LLM válasz: cloud: … -> edge: felelt (…)` | melyik agy felelt és miért |

---

## 8. Modell és HF Space publikálás `[dev]`

### HF chat-logok letöltése

```
hf download jabba77/szabi-chat-logs --repo-type dataset --local-dir ./szabi-logs
```

### A v12 modell kirakása a HF Space-re

> ⚠️ **KÉT lépés kell, és a második NEM hagyható ki.** A Space az **adaptert** tölti
> (`hf-space/app.py` → `ADAPTER_REPO`), tehát a feltöltés önmagában nem vált modellt.
> És a Space forrása a **REPÓ**: a `.github/workflows/deploy-hf-space.yml` minden
> `main`-re pusholt `hf-space/**` változásnál felülírja a Space-t. Egy kézi
> `hf upload spaces/...` csak a következő `main`-pushig él (ezt a #41 tanulta meg).

#### 1. Az adapter feltöltése HF-re

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

#### 2. A Space átállítása — feature branch + PR, NEM kézi upload

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

#### 3. Ellenőrzés, hogy tényleg fut

```
curl -s https://huggingface.co/api/spaces/jabba77/Szabi-Chat | python3 -m json.tool | grep -A2 runtime
```

`runtime.stage` legyen `RUNNING`. A build 2-4 perc; addig `BUILDING`.

#### 4. Ha a korpusz is változott

A Space a **becsomagolt** korpuszt tölti, nem építi:

```
(cd robot && uv run freedroid-corpus)   # a `-m` alak ma NEM megy, ld. 1. szakasz
cp training/rag/yotengrit_corpus.json hf-space/yotengrit_corpus.json
```

Enélkül a RAG-javítás nem ér el a Space-re (ezt a #47 tanulta meg). A
`test_hf_space_bundle.py` őrzi — ha piros, ez maradt ki.

### Ollama a keor-on (nincs systemd)

```
export OLLAMA_MODELS=$HOME/.ollama/models
nohup ollama serve > /tmp/ollama.log 2>&1 &
ollama list
```

### Egy letöltött fine-tune regisztrálása Ollamába

Az Unsloth `Modelfile`-ját **ne** használd (nincs benne SYSTEM, `temperature 1.5`):

```
cd training
python3 make_modelfile.py --variant llama8b \
    tests/v12/llama3.1-8b-v12/gguf-q4_k_m_gguf/Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf
cd tests/v12/llama3.1-8b-v12/gguf-q4_k_m_gguf
ollama create szabi-8b-v12 -f Modelfile_Meta-Llama-3.1-8B-Instruct.Q4_K_M
```

---

## 9. Git

```bash
git checkout -b feature/<angol-nev>          # SOHA ne a main-en dolgozz
cd robot && uv run ruff check . && uv run pytest -q      # commit ELŐTT
git commit -F - <<'EOF'                      # IDÉZŐJELES heredoc, mindig
…
EOF
gh api repos/pits2022/free-droid/issues/comments/<id> --jq '.body'   # review elolvasása
```

> ⚠️ **`git stash` TILOS ebben a repóban** (a Teremtő szabálya, 2026-08-13, valódi
> munkába került). Egy branchen dolgozz; ha váltani kell, WIP-commit.
> ⚠️ Idézőjel nélküli heredocban a shell lefuttatja a backtickeket — 2026-08-13-án egy
> commit-üzenetből így tűnt el egy sor.

---

## 10. Demó előtti sorrend

```bash
# 1. felhő
cd infra/terraform && python3 gpu_pick.py
terraform apply -var do_gpu_size=<slug> -var do_region=<slug>
# 2. alagút (LIMIT NÉLKÜL!)
cd ../ansible && ansible-playbook -i inventory.ini site.yml --tags wireguard --ask-vault-pass
# 3. a Pi a legfrissebb kódra
ssh creator@free-droid-001.home 'cd /opt/free-droid && git pull && sudo systemctl restart freedroid'
# 4. önteszt
ssh creator@free-droid-001.home 'cd /opt/free-droid/robot && uv run freedroid-health'
# 5. 🔴 a magánadat törlése — a demó NEM debug posztúrában megy
ssh creator@free-droid-001.home 'sudo rm -f /var/log/freedroid/transcript.jsonl*'
```
