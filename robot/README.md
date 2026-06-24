# robot/ — Free-Droid (Szabi) control software

RPi 5 Python control stack. This is a **scaffold**: interfaces + stubs only, no implementation yet
(Phase 4 in `docs/free-droid.md` — depends on assembled hardware + a fine-tuned model + the cloud).

The spec's `robot/` module list is realized as the `freedroid` package (`src/freedroid/`):

| Spec module | Package | Responsibility |
| :--- | :--- | :--- |
| `config/` | `freedroid.config` | GPIO pinout + tunables (thresholds, speeds, endpoints) — **build first; everything reads from here** |
| `motion/` | `freedroid.motion` | Cytron HAT-MDD10 track control (lgpio) — `move/turn/stop/set_speed`; closed value domains in `motion.types` |
| `motion/` (camera) | `freedroid.camera` | Camera pan/tilt servos via PCA9685 — `pan/tilt/action` (distinct from the track motors) |
| `safety/` | `freedroid.safety` | HC-SR04P ultrasonic watchdog on a separate thread — `stop()` below threshold, bypassing the LLM |
| `tools/` | `freedroid.tools` | `<tool>fn(k=v)</tool>` parser + handler registry |
| `llm/` | `freedroid.llm` | LLM client with cloud (WireGuard→Ollama) → edge fallback |
| `voice/` | `freedroid.voice` | wake word → STT → TTS → VAD (all offline) |
| `orchestrator/` | `freedroid.orchestrator` | main async loop tying it together + safe-mode |
| — | `freedroid.health` | vital-function checks (network/hardware/software), self-heal → safe-mode; `freedroid-health` CLI |

## Design invariants (from the spec — do not break when implementing)

- The **LLM never drives motors directly**. It emits a `<tool>` call; `tools` + `motion` execute it deterministically.
- The **safety watchdog is independent of the LLM** — an obstacle stops the robot regardless of model output.
- `scan_wifi()` is **read-only** — list networks via `nmcli`, never connect, never handle passwords.
- **Pi-only**: code is written directly against `lgpio`; there is no off-Pi mock backend.

## Health checks (`freedroid.health`)

Vital-function self-check that runs **at boot and on a 10-min timer** on the Pi
(systemd `freedroid-health.timer`). Three layers:

- **network** — WireGuard up, cloud Ollama reachable. *Cloud is on-demand, so these
  are WARNING (the edge fallback covers an outage), never a vital failure.*
- **hardware** — GPIO chip, I²C/SPI buses, USB mic/speaker, camera, thermal, disk.
- **software** — edge Ollama + model, orchestrator service, package import, voice binaries.

On a **vital** (CRITICAL) failure it **self-heals** (restart the relevant service),
re-checks, and if still failing enters **safe-mode** (writes `/run/freedroid/safe_mode`;
the orchestrator reads it to disable motion). It writes `/run/freedroid/health.json`,
logs to journald, and exits non-zero. Run manually: `freedroid-health`.

## Dev (managed with uv)

```bash
cd robot
uv sync --extra dev           # create venv + install
uv run freedroid              # run the orchestrator (once implemented)
uv run freedroid-health       # run the vital-function check once
uv run pytest                 # full suite
uv run pytest -m phase4       # the TDD harness (xfail until implemented)
uv run ruff check .
```

### Test layout

- **Green now:** `test_config`, `test_motion_types`, `test_grammar` (dataset↔enum
  contract), `test_interfaces`, and all `test_health_*` (the runtime health logic).
- **TDD harness (xfail, strict):** `test_parser_behaviour` and `test_phase4_hardware`
  describe intended Phase-4 behaviour. They xfail until implemented — and because
  `xfail_strict=true`, the moment an implementation makes one pass, the suite fails
  and forces removing the marker, turning the spec into a live guard.
- Hardware-controller specs are `@requires_pi` (skipped off-Pi).
