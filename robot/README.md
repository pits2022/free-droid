# robot/ — Free-Droid (Szabi) control software

RPi 5 Python control stack. This is a **scaffold**: interfaces + stubs only, no implementation yet
(Phase 4 in `docs/free-droid.md` — depends on assembled hardware + a fine-tuned model + the cloud).

The spec's `robot/` module list is realized as the `freedroid` package (`src/freedroid/`):

| Spec module | Package | Responsibility |
| :--- | :--- | :--- |
| `config/` | `freedroid.config` | GPIO pinout + tunables (thresholds, speeds, endpoints) — **build first; everything reads from here** |
| `motion/` | `freedroid.motion` | Cytron HAT-MDD10 control (lgpio) — `move/turn/stop/set_speed` |
| `safety/` | `freedroid.safety` | HC-SR04P ultrasonic watchdog on a separate thread — `stop()` below threshold, bypassing the LLM |
| `tools/` | `freedroid.tools` | `<tool>fn(k=v)</tool>` parser + handler registry |
| `llm/` | `freedroid.llm` | LLM client with cloud (WireGuard→Ollama) → edge fallback |
| `voice/` | `freedroid.voice` | wake word → STT → TTS → VAD (all offline) |
| `orchestrator/` | `freedroid.orchestrator` | main async loop tying it together + safe-mode |

## Design invariants (from the spec — do not break when implementing)

- The **LLM never drives motors directly**. It emits a `<tool>` call; `tools` + `motion` execute it deterministically.
- The **safety watchdog is independent of the LLM** — an obstacle stops the robot regardless of model output.
- `scan_wifi()` is **read-only** — list networks via `nmcli`, never connect, never handle passwords.
- **Pi-only**: code is written directly against `lgpio`; there is no off-Pi mock backend.

## Dev (managed with uv)

```bash
cd robot
uv sync --extra dev           # create venv + install
uv run freedroid              # run the orchestrator (once implemented)
uv run pytest
uv run ruff check .
```
