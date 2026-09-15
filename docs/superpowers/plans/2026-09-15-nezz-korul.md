# „Nézz körül" — előbb a kamera, aztán a kép: implementációs terv

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A látás-körben a kamera ELŐBB a kért pózba áll (körbenézés: előre/balra/jobbra; egyirányú: fent/lent/balra/jobbra), és csak UTÁNA készül a kép — képenként egy VLM-hívással, irány-címkével.

**Architecture:** A router egy nézési tervet ad (`vision_plan()` → `Station`-ök), az orchestrátor `_latvany()`-ja hajtja végre: póz → beállás → kép → VLM → címkézett sor. Nincs új tool, a látás-kapu (`LATAS_KORBEN_ENGEDETT = {stop}`) érintetlen. A kamera abszolút pózt kap (`move_to()`) a meglévő holtjáték-kompenzált úton.

**Tech Stack:** Python 3.13, `uv`, pytest (`xfail_strict=true`), ruff. Pi-only hardver: PCA9685 (adafruit), V4L2 (OpenCV).

**Spec:** `docs/superpowers/specs/2026-09-15-nezz-korul-design.md` (PR #135)

## Global Constraints

- **Előfeltétel: a PR #136 (`fix/vision-router-stt-wifi`) merge-elve** — a router STT-tűrése és hálózati tiltása (`_NETWORK_TOKENS`, `_WI_FI`, `_VISION_TOKEN_SETS`) erre épül. Branch: `feature/look-around` a friss `origin/main`-ről.
- **Új függvény- és változónevek ANGOLUL** (a Teremtő szabálya). A meglévő magyar azonosítókhoz (`_latvany`, `kell_e_kep`, `_LATAS_KIFEJEZESEK`…) NEM nyúlunk. A robot működéséhez magyar SZTRINGEK (címkék `Előre`/`Balra`/`Jobbra`/`Fent`/`Lent`, a `[LÁTVÁNY]` sorai) magyarok maradnak.
- Feature branch, soha nem `main`. **Push NINCS automatikusan.** `uv run ruff check .` commit ELŐTT.
- **Commit-üzenet MINDIG idézőjeles heredoc** (`git commit -F - <<'EOF'`). **SOHA `git stash`.**
- Minden parancs a `robot/` könyvtárból: `uv run pytest -q`, `uv run ruff check .`.
- **Egyetlen képkocka sem kerülhet lemezre** (VLM spec §5). A leírás szövege csak DEBUG-on naplózható.
- A `LATAS_KORBEN_ENGEDETT` és a `KNOWN_TOOLS` NEM változik.
- Szögek: a `move_to(pan_deg, tilt_deg)` szemantikája **pozitív pan = balra, pozitív tilt = fel**; a kamera a `G.PAN_LEFT_SIGN` / `G.TILT_UP_SIGN` előjellel fordítja a belső szögre. Mért tartomány: pan +56,4° / −78,9°, tilt ±53,6°.
- Alapértékek (spec §3.3): `look_side_deg = 45.0`, `look_up_deg = 30.0`, `look_down_deg = 30.0`, `settle_s = 0.5`.
- Blokk-sorok (spec §4): `A fejed most nem mozdul, csak előre látsz.` · `<címke>: nem adott képet a kamera.` · `<címke>: a fejem nem fordult oda.`

**Egy tudatos eltérés a spec szövegétől (a Task 3 javítja a specben is):** a spec `ask(kerdes, stop_event=None)` paramétert írt. A `tests/test_run_hurok.py` TÍZ helyen cseréli az `ask`-ot egyargumentumos lambdára (`lambda k: …`) — egy új paraméter mind a tizet eltörné. Ehelyett a meglévő minta: a hurok a kör előtt beállítja a `self._stop_event = trigger.allj` attribútumot, pontosan ahogy ma a `self._halasztott = []`-t. A viselkedés ugyanaz.

---

## Fájlszerkezet

| Fájl | Változás | Felelősség |
| :- | :- | :- |
| `robot/src/freedroid/config/settings.py` | Módosul | `VisionSettings`: 4 új mező + validáció |
| `robot/src/freedroid/camera/__init__.py` | Módosul | `CameraController.move_to` Protocol + `PanTiltCamera.move_to()` |
| `robot/src/freedroid/vision/router.py` | Módosul | `Station`, `vision_plan()`; `kell_e_kep()` burok |
| `robot/src/freedroid/orchestrator/__init__.py` | Módosul | `_latvany()` a tervet hajtja végre; `_look()`; `_stop_event` |
| `robot/tests/test_camera_move_to.py` | Új | `move_to()` hardver nélkül |
| `robot/tests/test_vision_router.py` | Módosul | `vision_plan()` táblázat |
| `robot/tests/test_orchestrator_look.py` | Új | a végrehajtás sorrendje és hibaágai |
| `robot/tests/test_orchestrator_execute.py`, `robot/tests/test_tool_handlers.py` | Módosul | a `FakeCamera` kap `move_to`-t (Protocol-hűség) |
| `docs/superpowers/specs/2026-09-15-nezz-korul-design.md` | Módosul | a `stop_event` átadásának módja |

---

### Task 1: Beállítások + `PanTiltCamera.move_to()`

**Files:**
- Modify: `robot/src/freedroid/config/settings.py` (`VisionSettings`, a `num_ctx` mező után és a `__post_init__`-ben)
- Modify: `robot/src/freedroid/camera/__init__.py` (`CameraController` Protocol; `PanTiltCamera` a `home()` után)
- Modify: `robot/tests/test_orchestrator_execute.py:61-75`, `robot/tests/test_tool_handlers.py:41-55` (`FakeCamera`)
- Test: `robot/tests/test_camera_move_to.py` (új)

**Interfaces:**
- Produces: `VisionSettings.look_side_deg: float`, `.look_up_deg: float`, `.look_down_deg: float`, `.settle_s: float`
- Produces: `CameraController.move_to(self, pan_deg: float, tilt_deg: float) -> bool` — `True`, ha bármelyik tengely ténylegesen elmozdult (ekkor kell `settle_s`), `False`, ha már ott állt.

- [ ] **Step 1: A bukó tesztek megírása**

`robot/tests/test_camera_move_to.py`:

```python
"""`PanTiltCamera.move_to()` — abszolút póz a holtjáték-kompenzált úton.

A konstruktor Pi-only (I2C, PCA9685), ezért a példány `object.__new__`-val készül és csak
a kiadó ág (`_kiad`) van kicserélve — mint a `test_camera_home.py`-ban. A vizsgált logika
a VALÓDI kód.
"""

from __future__ import annotations

import pytest

from freedroid.camera import PanTiltCamera, tengelyek
from freedroid.config import gpio as G
from freedroid.config.settings import Settings, VisionSettings, load_settings


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("freedroid.camera.time.sleep", lambda s: None)


def camera() -> tuple[PanTiltCamera, list[tuple[str, float]]]:
    cfg = load_settings().camera
    k = object.__new__(PanTiltCamera)
    k._cfg = cfg
    k._pan_t, k._tilt_t = tengelyek(cfg)
    k._szog = {"pan": 0.0, "tilt": 0.0}
    k._tiszta = {"pan", "tilt"}
    outputs: list[tuple[str, float]] = []
    k._kiad = lambda t, szog: outputs.append((t.nev, szog))  # type: ignore[method-assign]
    return k, outputs


def test_move_to_reaches_the_absolute_target_with_sign():
    k, outputs = camera()
    assert k.move_to(45.0, -30.0) is True
    assert k._szog == {"pan": G.PAN_LEFT_SIGN * 45.0, "tilt": G.TILT_UP_SIGN * -30.0}
    # az UTOLSÓ kiadás tengelyenként maga a cél (előtte jöhet a holtjáték-alálövés)
    last = {name: angle for name, angle in outputs}
    assert last == {"pan": G.PAN_LEFT_SIGN * 45.0, "tilt": G.TILT_UP_SIGN * -30.0}


def test_move_to_is_absolute_not_relative():
    k, _ = camera()
    k.move_to(45.0, 0.0)
    k.move_to(-45.0, 0.0)
    assert k._szog["pan"] == G.PAN_LEFT_SIGN * -45.0


def test_move_to_current_pose_does_not_move():
    """A kör eleji `home()` után az `Előre (0, 0)` NEM mozdít — és nem kell rá `settle_s`."""
    k, outputs = camera()
    assert k.move_to(0.0, 0.0) is False
    assert outputs == []


def test_move_to_zero_is_a_real_target():
    """`bool(0.0)` hamis — a 0 fok mégis érvényes cél, ha máshol áll a fej."""
    k, outputs = camera()
    k.move_to(45.0, 0.0)
    outputs.clear()
    assert k.move_to(0.0, 0.0) is True
    assert ("pan", 0.0) in outputs


def test_move_to_clips_out_of_range_target(caplog):
    k, _ = camera()
    k.move_to(999.0, 0.0)
    assert abs(k._szog["pan"]) < 999.0
    assert "határon kívül" in caplog.text


@pytest.mark.parametrize("field", ["look_side_deg", "look_up_deg", "look_down_deg", "settle_s"])
def test_non_positive_look_settings_fail_at_startup(field):
    with pytest.raises(ValueError, match=f"vision.{field}"):
        VisionSettings(**{field: 0.0})


def test_look_settings_defaults():
    v = Settings().vision
    assert (v.look_side_deg, v.look_up_deg, v.look_down_deg, v.settle_s) == (45.0, 30.0, 30.0, 0.5)
```

- [ ] **Step 2: Futtatás — bukniuk kell**

Run: `cd robot && uv run pytest -q tests/test_camera_move_to.py`
Expected: FAIL — `AttributeError: 'PanTiltCamera' object has no attribute 'move_to'` és `TypeError: unexpected keyword argument 'look_side_deg'`.

- [ ] **Step 3: `VisionSettings` mezők + validáció**

`robot/src/freedroid/config/settings.py`, a `num_ctx: int = 2048` sor UTÁN:

```python
    # A NÉZÉSI TERV pózai („nézz körül" / „nézz fel, mit látsz") — spec 2026-09-15-nezz-korul.
    # A kamera széles látószögű, a ±45 fok három képpel lefedi a teret (a Teremtő). Mért
    # tartomány: pan +56,4 / -78,9 fok, tilt ±53,6 fok — mindegyik belefér.
    look_side_deg: float = 45.0
    look_up_deg: float = 30.0
    look_down_deg: float = 30.0
    # Pózváltás UTÁN, a kép ELŐTT: a szervó beállása + a rázkódás lecsengése. Hardver-
    # hangoló; csak valódi mozdulás után várunk (`move_to()` visszatérési értéke).
    settle_s: float = 0.5
```

és a `__post_init__` meglévő ciklusában bővítsd a mezőlistát:

```python
        for nev in ("timeout_s", "probe_timeout_s", "warmup_timeout_s", "num_ctx",
                    "look_side_deg", "look_up_deg", "look_down_deg", "settle_s"):
            if getattr(self, nev) <= 0:
                raise ValueError(f"vision.{nev} must be > 0")
```

- [ ] **Step 4: `move_to()` a kamerában**

`robot/src/freedroid/camera/__init__.py`, a `CameraController` Protocolba a `home` után:

```python
    def move_to(self, pan_deg: float, tilt_deg: float) -> bool: ...
```

a `PanTiltCamera.home()` metódus UTÁN:

```python
    def move_to(self, pan_deg: float, tilt_deg: float) -> bool:
        """ABSZOLÚT póz: pozitív pan = balra, pozitív tilt = fel. `True`, ha mozdult.

        A nézési terv (spec 2026-09-15-nezz-korul) erre épül, nem a `pan`/`tilt`-re: azok
        RELATÍVAK és hozzávetőlegesek (holtjáték nélkül), egy „balra 45, majd jobbra 45 a
        KÖZÉPHEZ képest" pedig abszolút célokat kér. A holtjáték-kompenzált út
        (`_beall_holtjatek_nelkul`) mindig ugyanabból az irányból érkezik, tehát a kép
        ugyanabból a pózból készül, akárhonnan jött a fej.

        A visszatérési érték a hívóé: CSAK valódi mozdulás után kell kivárni a beállást —
        a kör eleji `home()` után az `Előre (0, 0)` egy tizedmásodpercet sem várhat.
        """
        moved = False
        for axis, sign, requested in ((self._pan_t, G.PAN_LEFT_SIGN, pan_deg),
                                      (self._tilt_t, G.TILT_UP_SIGN, tilt_deg)):
            target = vagott_szog(axis, sign * requested)
            if target != sign * requested:
                log.warning("%s: %.1f fok a határon kívül, vágva %.1f fokra",
                            axis.nev, sign * requested, target)
            if self._szog[axis.nev] == target:
                continue
            self._beall_holtjatek_nelkul(axis, target)
            moved = True
        return moved
```

- [ ] **Step 5: A teszt-dublőrök Protocol-hűsége**

`robot/tests/test_orchestrator_execute.py`, a `FakeCamera.home` metódus UTÁN (ez a dublőr sztringeket naplóz):

```python
    def move_to(self, pan_deg: float, tilt_deg: float) -> bool:
        self.calls.append("move_to")
        return True
```

`robot/tests/test_tool_handlers.py`, a `FakeCamera.home` metódus UTÁN (ez a dublőr tuple-öket naplóz):

```python
    def move_to(self, pan_deg: float, tilt_deg: float) -> bool:
        self.calls.append(("move_to", pan_deg, tilt_deg))
        return True
```

- [ ] **Step 6: Futtatás — zöld**

Run: `cd robot && uv run pytest -q tests/test_camera_move_to.py tests/test_camera_home.py && uv run pytest -q && uv run ruff check .`
Expected: PASS mindenhol; a teljes csomag zöld.

- [ ] **Step 7: Commit**

```bash
git add robot/src/freedroid/config/settings.py robot/src/freedroid/camera/__init__.py \
        robot/tests/test_camera_move_to.py robot/tests/test_orchestrator_execute.py \
        robot/tests/test_tool_handlers.py
git commit -F - <<'EOF'
feat(camera): move_to() abszolút póz + a nézési terv beállításai

A „nézz körül" spec (2026-09-15) alapja: abszolút póz (pozitív pan = balra,
pozitív tilt = fel) a holtjáték-kompenzált úton, True-t ad, ha mozdult — a
beállási várakozás csak ekkor kell. VisionSettings: look_side_deg 45,
look_up_deg 30, look_down_deg 30, settle_s 0,5 (mind > 0).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: A router nézési terve — `Station`, `vision_plan()`

**Files:**
- Modify: `robot/src/freedroid/vision/router.py` (új importok a tetején; új kód a `kell_e_kep()` HELYÉN)
- Modify: `robot/tests/test_vision_router.py` (új tesztek a fájl végére)

**Interfaces:**
- Consumes: semmit a Task 1-ből (a router tiszta függvény, a szögeket paraméterben kapja).
- Produces:
  - `@dataclass(frozen=True) class Station: label: str | None; pan_deg: float | None; tilt_deg: float | None`
  - `def vision_plan(question: str, *, side_deg: float = 45.0, up_deg: float = 30.0, down_deg: float = 30.0) -> tuple[Station, ...] | None`
  - `kell_e_kep(kerdes) == (vision_plan(kerdes) is not None)` — változatlan név és viselkedés a meglévő kérdésekre.
  - Címkék pontosan: `"Előre"`, `"Balra"`, `"Jobbra"`, `"Fent"`, `"Lent"`.

- [ ] **Step 1: A bukó tesztek megírása**

A `robot/tests/test_vision_router.py` importját bővítsd:

```python
from freedroid.vision.router import Station, _ellenorzi_uresek_ellen, kell_e_kep, vision_plan
```

és a fájl végére:

```python
LOOK_AROUND = (Station("Előre", 0.0, 0.0), Station("Balra", 45.0, 0.0),
               Station("Jobbra", -45.0, 0.0))


@pytest.mark.parametrize("question", [
    "Nézz körül és mondd el, mit látsz.",
    "Nézz körül a kameráddal!",
    "Nézz szét a szobában!",
    "Nézzél körül!",
    "Pásztázz körbe a kameráddal!",
    "Nézz körbe!",
])
def test_look_around_is_three_stations(question):
    assert vision_plan(question) == LOOK_AROUND


@pytest.mark.parametrize("question, station", [
    ("Nézz fel és mondd el, mit látsz.", Station("Fent", 0.0, 30.0)),
    ("Nézz felfelé, mit látsz?", Station("Fent", 0.0, 30.0)),
    ("Nézz a plafonra, mit látsz?", Station("Fent", 0.0, 30.0)),
    ("Nézz le és mondd el, mit látsz.", Station("Lent", 0.0, -30.0)),
    ("Nézz a földre, és mondd el, mit látsz előtted.", Station("Lent", 0.0, -30.0)),
    ("Nézz lefelé és mond el, mit látsz.", Station("Lent", 0.0, -30.0)),
    ("Nézz balra, mit látsz?", Station("Balra", 45.0, 0.0)),
    ("Nézz jobbra és mondd el, mit látsz!", Station("Jobbra", -45.0, 0.0)),
])
def test_direction_with_vision_cue_is_one_labelled_station(question, station):
    assert vision_plan(question) == (station,)


def test_bare_look_up_is_NOT_a_vision_question():
    """A csupasz „Nézz fel!" kamera-parancs a modelltől, nem látás-kör (spec §3.1)."""
    assert vision_plan("Nézz fel!") is None
    assert vision_plan("Nézz balra!") is None


def test_direction_word_must_follow_the_verb():
    """„Nézz rám és írd le, mit látsz" — a `le` az „írd le" része, nem irány."""
    assert vision_plan("Nézz rám és írd le, mit látsz!") == (Station(None, None, None),)


def test_plain_vision_question_keeps_the_current_pose():
    assert vision_plan("Mit látsz?") == (Station(None, None, None),)


def test_angles_come_from_the_caller():
    plan = vision_plan("Nézz körül!", side_deg=30.0)
    assert [s.pan_deg for s in plan] == [0.0, 30.0, -30.0]
    assert vision_plan("Nézz fel, mit látsz?", up_deg=20.0) == (Station("Fent", 0.0, 20.0),)


def test_network_block_applies_to_every_branch():
    assert vision_plan("Nézz körül a wifin!") is None
    assert vision_plan("Nézz fel és mondd, milyen hálózatot látsz!") is None


@pytest.mark.parametrize("question", LATAS + NEM_LATAS)
def test_kell_e_kep_is_a_thin_wrapper(question):
    assert kell_e_kep(question) == (vision_plan(question) is not None)
```

- [ ] **Step 2: Futtatás — bukniuk kell**

Run: `cd robot && uv run pytest -q tests/test_vision_router.py`
Expected: FAIL — `ImportError: cannot import name 'Station'`.

- [ ] **Step 3: Implementáció**

`robot/src/freedroid/vision/router.py` importjai:

```python
from dataclasses import dataclass

from freedroid.rag.normalize import _TOKEN, _fold, tokenize
```

A `def kell_e_kep(...)` TELJES régi törzsét cseréld erre (a felette lévő konstansok és `_ellenorzi_uresek_ellen` maradnak):

```python
@dataclass(frozen=True)
class Station:
    """A nézési terv egy állomása. `None` szög = maradjon az aktuális póz; `None` címke =
    a sor címke nélkül kerül a `[LÁTVÁNY]` blokkba (spec §3.4/5)."""

    label: str | None
    pan_deg: float | None
    tilt_deg: float | None


# Körbenézés — a „nézz körül" már a látás-kifejezések közt van; ezek a TÖBB-állomásos ág.
_LOOK_AROUND_PHRASES = ("nézz körül", "nézz körbe", "nézz szét", "nézzél körül",
                        "nézzél szét", "pásztázz körbe")
_LOOK_AROUND_TOKEN_SETS = tuple(frozenset(tokenize(p)) for p in _LOOK_AROUND_PHRASES)
_ellenorzi_uresek_ellen(_LOOK_AROUND_PHRASES,
                        tuple(tuple(tokenize(p)) for p in _LOOK_AROUND_PHRASES))

# 🔴 Az irány a stopszó-szűrés ELŐTTI szavakon dől el: a „fel" és a „le" STOPSZÓ, a
# `tokenize("nézz fel")` és a `tokenize("nézz le")` egyaránt `['nezz']` (mérve,
# 2026-09-15). Az ékezetfosztás a `rag.normalize` segédjeivel megy, nem egy másodikkal.
_LOOK_VERBS = frozenset({"nezz", "nezzel"})
_DIRECTION_WORDS = {
    "up": frozenset({"fel", "felfele", "plafonra", "mennyezetre"}),
    "down": frozenset({"le", "lefele", "foldre"}),
    "left": frozenset({"balra"}),
    "right": frozenset({"jobbra"}),
}
# Az irányszó legfeljebb ennyi szóval követheti az igét: „nézz a földre" (a névelő
# átugorható), de „Nézz rám és írd le" NEM lefelé nézés.
_DIRECTION_WINDOW = 2


def _is_network_question(tokens: set[str]) -> bool:
    return (not tokens.isdisjoint(_NETWORK_TOKENS) or _WI_FI <= tokens
            or any(t.startswith("wifi") for t in tokens))


def _direction(question: str) -> str | None:
    words = _TOKEN.findall(_fold(question))
    for i, word in enumerate(words):
        if word not in _LOOK_VERBS:
            continue
        for following in words[i + 1:i + 1 + _DIRECTION_WINDOW]:
            for direction, direction_words in _DIRECTION_WORDS.items():
                if following in direction_words:
                    return direction
    return None


def vision_plan(question: str, *, side_deg: float = 45.0, up_deg: float = 30.0,
                down_deg: float = 30.0) -> tuple[Station, ...] | None:
    """A kérdés nézési terve, vagy `None`, ha nem kell kép (spec §3.1).

    Prioritás: hálózati kérdés → `None`; körbenézés → három állomás; irány + látás-jel →
    egy címkézett állomás; sima látás-kérdés → egy állomás az aktuális pózból.
    """
    tokens = set(tokenize(question))
    if _is_network_question(tokens):
        return None
    if any(s <= tokens for s in _LOOK_AROUND_TOKEN_SETS):
        return (Station("Előre", 0.0, 0.0), Station("Balra", side_deg, 0.0),
                Station("Jobbra", -side_deg, 0.0))
    if not any(s <= tokens for s in _VISION_TOKEN_SETS):
        return None
    poses = {"up": Station("Fent", 0.0, up_deg), "down": Station("Lent", 0.0, -down_deg),
             "left": Station("Balra", side_deg, 0.0), "right": Station("Jobbra", -side_deg, 0.0)}
    direction = _direction(question)
    if direction is not None:
        return (poses[direction],)
    return (Station(None, None, None),)


def kell_e_kep(kerdes: str) -> bool:
    """Igaz, ha a kérdés a kamerakép nélkül nem válaszolható meg becsületesen."""
    return vision_plan(kerdes) is not None
```

- [ ] **Step 4: Futtatás — zöld**

Run: `cd robot && uv run pytest -q tests/test_vision_router.py && uv run pytest -q && uv run ruff check .`
Expected: PASS. Ha a `test_kell_e_kep_is_a_thin_wrapper` egy MEGLÉVŐ `LATAS`/`NEM_LATAS` tételen bukik, az viselkedésváltozás — állj meg és jelezd, ne a tesztet igazítsd.

- [ ] **Step 5: Regresszió a 2026-09-15-i élő menetre**

Run (a helyi gépen, ahol a napló van):

```bash
cd robot && uv run python - <<'EOF'
import json
from freedroid.vision.router import vision_plan
rows = [json.loads(l) for l in open("/home/csaba/free-droid-logs/transcript-2026-09-15.jsonl", encoding="utf-8")]
for r in rows:
    plan = vision_plan(r["hallott"])
    if plan and plan[0].label is not None:
        print([s.label for s in plan], repr(r["hallott"]))
EOF
```

Expected: címkékkel CSAK a körbenéző és irányos kérdések jelennek meg — #4 „Nézz körül és mondd el…", #26 „Nézz a földre…" (`Lent`), #28 „Nézz lefelé…" (`Lent`), #44 „Nézz körül és pásztálsz körbe", #45 „Nézz fel és pasztás körbe" (a `nézz körbe` párja miatt körbenézés), #80 és #150 „Nézz körül a kameráddal…". NEM jelenhet meg: #29 „Nézz előre…" (nincs ilyen irány — sima kérdés, címke nélkül). Ha ettől eltér, állj meg és jelezd. Az eredményt írd be a commit-üzenetbe.

- [ ] **Step 6: Commit**

```bash
git add robot/src/freedroid/vision/router.py robot/tests/test_vision_router.py
git commit -F - <<'EOF'
feat(vision): a router nézési tervet ad — Station, vision_plan()

Spec 2026-09-15-nezz-korul §3.1: körbenézés -> Előre/Balra/Jobbra; irány +
látás-jel -> egy címkézett állomás (Fent/Lent/Balra/Jobbra); sima látás-kérdés
-> egy állomás az aktuális pózból. A hálózati tiltás minden ágra érvényes.
A „fel"/„le" stopszó, ezért az irány a szűrés előtti szavakon dől el, és az
irányszónak az igét kell követnie („Nézz rám és írd le" nem lefelé nézés).
A kell_e_kep() egysoros burok lett.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Az orchestrátor végrehajtja a tervet

**Files:**
- Modify: `robot/src/freedroid/orchestrator/__init__.py` (`__init__`: `_stop_event` attribútum; `_latvany()` törzse; új `_look()`; `_egy_kor`: a `self._halasztott = []` sor mellé)
- Modify: `docs/superpowers/specs/2026-09-15-nezz-korul-design.md` (§3.4 utolsó bekezdése)
- Test: `robot/tests/test_orchestrator_look.py` (új)

**Interfaces:**
- Consumes: `vision_plan(question, *, side_deg, up_deg, down_deg)`, `Station` (Task 2); `CameraController.move_to(pan_deg, tilt_deg) -> bool`, `VisionSettings.look_side_deg/look_up_deg/look_down_deg/settle_s` (Task 1).
- Produces: `Orchestrator._look(self, plan: tuple[Station, ...], cfg: VisionSettings) -> tuple[list[str], bool]` — a blokk sorai, és hogy készült-e legalább EGY valódi leírás (ha nem, a hívó `LATVANY_NINCS`-et ad); `Orchestrator._stop_event: threading.Event | None`; `HEAD_FIXED_NOTE` konstans.

- [ ] **Step 1: A bukó tesztek megírása**

`robot/tests/test_orchestrator_look.py`:

```python
"""A nézési terv végrehajtása — előbb a póz, aztán a kép (spec 2026-09-15-nezz-korul).

🔴 A kulcsteszt a 2026-09-15-i élő hibát fogja: ott a kép a mozdulat ELŐTT készült, a
„Nézz a földre" egy ajtót írt le, és a 8B „padlót" mondott. Itt minden képkockát meg kell
előznie a hozzá tartozó póznak — egy KÖZÖS eseménylistán mérve.
"""

from __future__ import annotations

import dataclasses
import threading

from freedroid.config.settings import Settings, VisionSettings
from freedroid.orchestrator import Orchestrator
from freedroid.rag.context import LATVANY_NINCS


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []


class FakeCamera:
    def __init__(self, rec: Recorder, *, fail_on: tuple[float, float] | None = None) -> None:
        self.rec, self.fail_on = rec, fail_on
        self.pose = (0.0, 0.0)

    def move_to(self, pan_deg: float, tilt_deg: float) -> bool:
        if (pan_deg, tilt_deg) == self.fail_on:
            raise OSError("I2C hiba")
        moved = (pan_deg, tilt_deg) != self.pose
        self.pose = (pan_deg, tilt_deg)
        self.rec.events.append(("move_to", pan_deg, tilt_deg))
        return moved

    def home(self) -> None: ...
    def pan(self, *a) -> None: ...
    def tilt(self, *a) -> None: ...
    def action(self, *a) -> None: ...
    def close(self) -> None: ...


class FakeVLM:
    def __init__(self, rec: Recorder, answers: list[str | None]) -> None:
        self.rec, self.answers = rec, list(answers)

    def elerheto(self) -> tuple[bool, str]:
        return True, "elérhető"

    def describe(self, jpeg: bytes) -> str | None:
        self.rec.events.append(("describe", jpeg))
        return self.answers.pop(0)


class DeadVLM(FakeVLM):
    def elerheto(self) -> tuple[bool, str]:
        return False, "nem elérhető"


class PromptLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Látom, Teremtőm."

    def active_backend(self):
        return None


class Stub:
    fault = None
    heading = None
    is_turning = False

    def __getattr__(self, _name):
        return lambda *a, **kw: None


def build(monkeypatch, rec, vlm, *, camera="fake", frames=None, **vision):
    frames = list(frames) if frames is not None else [b"f1", b"f2", b"f3"]

    def grab(*a, **kw):
        frame = frames.pop(0) if frames else None
        rec.events.append(("grab", frame))
        return frame

    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg", grab)
    sleeps: list[float] = []
    monkeypatch.setattr("freedroid.orchestrator.time.sleep", sleeps.append)
    settings = dataclasses.replace(Settings(), vision=VisionSettings(
        enabled=True, model="fake-vlm:latest", **vision))
    cam = FakeCamera(rec) if camera == "fake" else camera
    o = Orchestrator(settings=settings, llm=PromptLLM(), vlm=vlm, camera=cam,
                     motion=Stub(), watchdog=Stub())
    monkeypatch.setattr("freedroid.orchestrator.transcript.log", lambda *a, **k: None)
    monkeypatch.setattr(o, "_talalatok", lambda k: [])
    o.camera = cam
    return o, sleeps


def test_every_frame_is_preceded_by_its_pose(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", "egy ablak", "egy polc"]))
    o.ask("Nézz körül és mondd el, mit látsz.")
    kinds = [e[0] for e in rec.events]
    assert kinds == ["move_to", "grab", "describe", "move_to", "grab", "describe",
                     "move_to", "grab", "describe", "move_to"]
    assert rec.events[0] == ("move_to", 0.0, 0.0)
    assert rec.events[3] == ("move_to", 45.0, 0.0)
    assert rec.events[6] == ("move_to", -45.0, 0.0)
    assert rec.events[9] == ("move_to", 0.0, 0.0), "körbenézés után vissza középre"


def test_the_block_is_labelled_per_direction(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", "egy ablak", "egy polc"]))
    o.ask("Nézz körül!")
    prompt = o.llm.prompts[0]
    assert "Előre: egy ajtó\nBalra: egy ablak\nJobbra: egy polc" in prompt


def test_one_direction_is_labelled_and_stays_in_pose(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["a padló"]))
    o.ask("Nézz a földre, és mondd el, mit látsz.")
    assert "Lent: a padló" in o.llm.prompts[0]
    assert [e for e in rec.events if e[0] == "move_to"] == [("move_to", 0.0, -30.0)]


def test_plain_question_does_not_move_and_has_no_label(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy asztal"]))
    o.ask("Mit látsz?")
    assert [e[0] for e in rec.events] == ["grab", "describe"]
    assert "egy asztal" in o.llm.prompts[0] and "Előre:" not in o.llm.prompts[0]


def test_settle_only_after_a_real_move(monkeypatch):
    rec = Recorder()
    o, sleeps = build(monkeypatch, rec, FakeVLM(rec, ["a", "b", "c"]), settle_s=0.5)
    o.ask("Nézz körül!")
    # Előre (0,0) a kezdő pózban: nem mozdul -> nincs várakozás; Balra, Jobbra: igen.
    # A záró vissza-középre sem vár (nincs utána kép).
    assert sleeps == [0.5, 0.5]


def test_first_vlm_failure_stops_the_remaining_stations(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", None, "soha"]))
    o.ask("Nézz körül!")
    assert sum(1 for e in rec.events if e[0] == "describe") == 2
    assert "Előre: egy ajtó" in o.llm.prompts[0]
    assert "Jobbra:" not in o.llm.prompts[0]


def test_missing_frame_is_said_and_the_tour_goes_on(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", "egy polc"]),
                 frames=[b"f1", None, b"f3"])
    o.ask("Nézz körül!")
    assert "Balra: nem adott képet a kamera." in o.llm.prompts[0]
    assert "Jobbra: egy polc" in o.llm.prompts[0]


def test_move_to_error_keeps_earlier_descriptions(monkeypatch):
    rec = Recorder()
    cam = FakeCamera(rec, fail_on=(-45.0, 0.0))
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", "egy ablak"]), camera=cam)
    o.ask("Nézz körül!")
    assert "Előre: egy ajtó\nBalra: egy ablak\nJobbra: a fejem nem fordult oda." in o.llm.prompts[0]


def test_stop_event_stops_the_tour(monkeypatch):
    rec = Recorder()
    stop = threading.Event()

    class StoppingVLM(FakeVLM):
        def describe(self, jpeg):
            stop.set()
            return super().describe(jpeg)

    o, _ = build(monkeypatch, rec, StoppingVLM(rec, ["egy ajtó", "x", "y"]))
    o._stop_event = stop
    o.ask("Nézz körül!")
    assert sum(1 for e in rec.events if e[0] == "describe") == 1
    assert rec.events[-1][0] == "describe", "ÁLLJ után nincs több mozgás, vissza-középre sem"


def test_no_camera_controller_says_the_head_is_fixed(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó"]), camera=None)
    o.ask("Nézz körül!")
    prompt = o.llm.prompts[0]
    assert "A fejed most nem mozdul, csak előre látsz.\negy ajtó" in prompt
    assert "Balra:" not in prompt and "Jobbra:" not in prompt


def test_dead_tunnel_does_not_move_the_head(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, DeadVLM(rec, []))
    o.ask("Nézz körül!")
    assert rec.events == []
    assert LATVANY_NINCS in o.llm.prompts[0]


def test_no_description_at_all_gives_the_negative_block(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, [None]))
    o.ask("Nézz a földre, mit látsz?")
    assert LATVANY_NINCS in o.llm.prompts[0]
```

- [ ] **Step 2: Futtatás — bukniuk kell**

Run: `cd robot && uv run pytest -q tests/test_orchestrator_look.py`
Expected: FAIL — pl. `test_every_frame_is_preceded_by_its_pose`: az eseménylista `["grab", "describe"]` (a mai kód nem mozgat).

- [ ] **Step 3: `_stop_event` attribútum + átadás a hurokból**

`robot/src/freedroid/orchestrator/__init__.py`, az `__init__`-ben a `self._halasztott: list | None = None` sor UTÁN:

```python
        # Az ÁLLJ jelzője a látás-körnek (spec 2026-09-15-nezz-korul §5): a hurok a kör
        # előtt adja át, mint a `_halasztott`-at. Nem `ask()`-paraméter, mert a tesztek
        # tíz helyen egyargumentumos lambdára cserélik az `ask`-ot. `None` = szöveges út.
        self._stop_event: threading.Event | None = None
```

az `_egy_kor`-ban a `self._halasztott = []` sor UTÁN:

```python
            self._stop_event = trigger.allj
```

- [ ] **Step 4: `_latvany()` és `_look()`**

A modul tetején, a `MOZGATO_TOOLOK` konstansok közelében:

```python
# Ha a nézési terv mozgást kér, de nincs kamera-vezérlő (a szervó-vezérlő nem épült meg):
# ne találjon ki semmit oldalra/felfelé (spec §4).
HEAD_FIXED_NOTE = "A fejed most nem mozdul, csak előre látsz."
```

A `_latvany()` törzsében a meglévő, `from freedroid.rag.context import LATVANY_NINCS` sortól a metódus végéig tartó részt cseréld erre (a docstring marad):

```python
        from freedroid.config.settings import load_settings  # noqa: PLC0415
        from freedroid.rag.context import LATVANY_NINCS  # noqa: PLC0415
        from freedroid.vision.router import vision_plan  # noqa: PLC0415

        cfg = (self._settings or load_settings()).vision
        plan = vision_plan(kerdes, side_deg=cfg.look_side_deg, up_deg=cfg.look_up_deg,
                           down_deg=cfg.look_down_deg)
        if plan is None:
            return None
        if self.vlm is None:
            return LATVANY_NINCS
        try:
            # Az elérhetőség ELŐBB dől el, mint a kameramunka: halott alagútnál se póz,
            # se kép (`korben_elerhetetlen` cache, `probe_timeout_s`) — spec §4.
            elerheto, indok = self.vlm.elerheto()
            if not elerheto:
                log.info("látás kihagyva — %s", indok)
                return LATVANY_NINCS
            lines, described = self._look(plan, cfg)
            # Hiba-sorok („nem adott képet") önmagukban nem látvány: legalább EGY valódi
            # leírás kell, különben a negatív blokk megy (spec §4).
            return "\n".join(lines) if described else LATVANY_NINCS
        except Exception:  # noqa: BLE001 — a látás bukása nem némíthatja el a robotot
            log.warning("a látás elhasalt — Szabi most nem lát", exc_info=True)
            return LATVANY_NINCS

    def _look(self, plan, cfg) -> tuple[list[str], bool]:
        """A nézési terv végrehajtása: állomásonként póz -> beállás -> kép -> VLM -> sor.

        🔴 A SORREND a lényeg (mérve 2026-09-15): a kép a póz UTÁN készül. Egy állomás
        képkocka-hibája vagy szervó-hibája csak a SAJÁT sorát viszi; az első VLM-hiba
        viszont a hátralévő állomásokat is (host-baj valószínű — nincs háromszor 8 s csend).
        """
        from freedroid.camera.frame import grab_jpeg  # noqa: PLC0415
        from freedroid.vision.router import Station  # noqa: PLC0415

        lines: list[str] = []
        described = False
        needs_head = any(s.pan_deg is not None for s in plan)
        if needs_head and self.camera is None:
            lines.append(HEAD_FIXED_NOTE)
            plan = (Station(None, None, None),)
        stopped = False
        for station in plan:
            if self._stop_event is not None and self._stop_event.is_set():
                log.info("látás: ÁLLJ — a nézési terv megállt")
                stopped = True
                break
            prefix = f"{station.label}: " if station.label is not None else ""
            if station.pan_deg is not None:
                try:
                    moved = self.camera.move_to(station.pan_deg, station.tilt_deg)
                except Exception:  # noqa: BLE001 — egy szervó-hiba csak a saját sorát viszi
                    log.warning("látás: a fej nem állt be (%s)", station.label, exc_info=True)
                    lines.append(f"{prefix}a fejem nem fordult oda.")
                    continue
                if moved:
                    time.sleep(cfg.settle_s)
            started = time.monotonic()
            jpeg = grab_jpeg(cfg.device or None, minoseg=cfg.jpeg_quality)
            if jpeg is None:
                lines.append(f"{prefix}nem adott képet a kamera.")
                continue
            # 🔴 IDEGEN szöveg (egy felmutatott tábla is lehet) — PR #134, 1. réteg.
            description = idegen_szoveg_tisztit(self.vlm.describe(jpeg) or "")
            log.info("látás: %s állomás %.1f s", station.label or "egy", time.monotonic() - started)
            if not description:
                break
            lines.append(prefix + description)
            described = True
        if len(plan) > 1 and not stopped and self.camera is not None:
            try:
                self.camera.move_to(0.0, 0.0)   # spec §3.4/6: ne kitekerve beszéljen
            except Exception:  # noqa: BLE001
                log.warning("látás: a fej nem tért vissza középre", exc_info=True)
        return lines, described
```

- [ ] **Step 5: Futtatás — zöld, a meglévő látás-tesztekkel együtt**

Run: `cd robot && uv run pytest -q tests/test_orchestrator_look.py tests/test_orchestrator_vision.py tests/test_run_hurok.py && uv run pytest -q && uv run ruff check .`
Expected: PASS. A `test_orchestrator_vision.py` mostani tesztjei (`camera=None`, sima „Mit látsz?") változatlanul zöldek — az egyállomásos, póz nélküli út nem ír megjegyzést.

- [ ] **Step 6: A spec sorának javítása**

`docs/superpowers/specs/2026-09-15-nezz-korul-design.md`, a §3.4 végén cseréld ezt:

```markdown
Az `ask()` új, opcionális paramétere: `ask(kerdes, stop_event: threading.Event | None = None)`
— a hurok a `trigger.allj`-t adja át; a szöveges út (`ask_smoke`, tesztek) `None`-nal fut.
```

erre:

```markdown
A `stop_event`-et a hurok a kör előtt állítja be (`self._stop_event = trigger.allj`), mint a
`self._halasztott`-at — NEM `ask()`-paraméter, mert a `test_run_hurok.py` tíz helyen
egyargumentumos lambdára cseréli az `ask`-ot. A szöveges út (`ask_smoke`, tesztek) `None`-nal fut.
```

- [ ] **Step 7: Commit**

```bash
git add robot/src/freedroid/orchestrator/__init__.py robot/tests/test_orchestrator_look.py \
        docs/superpowers/specs/2026-09-15-nezz-korul-design.md
git commit -F - <<'EOF'
feat(vision): előbb a póz, aztán a kép — az orchestrátor végrehajtja a nézési tervet

A 2026-09-15-i élő menetben a kép a mozdulat ELŐTT készült: a „nézz körül"
pásztázásának nem volt értelme, a „Nézz a földre" egy ajtót írt le, és a 8B
„padlót" mondott. Most állomásonként: move_to -> (csak valódi mozdulás után)
settle_s -> grab_jpeg -> describe -> címkézett sor; körbenézés után vissza
középre. Hibaágak a spec §4 szerint: képkocka-hiba és szervó-hiba csak a saját
sorát viszi, az első VLM-hiba a hátralévőket is; ÁLLJ a következő állomás
előtt megállít; kamera-vezérlő nélkül „A fejed most nem mozdul". A
stop_event a hurok attribútuma (mint a _halasztott), nem ask()-paraméter.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Élő igazolás a Pi-n

**Files:**
- Nincs kódváltozás. Eredmény: a PR leírásába és a `WORKFLOW.md`-be.

**Interfaces:**
- Consumes: Task 1–3.

- [ ] **Step 1: Árnyék-telepítés a Pi-re (a branch még nincs merge-elve)**

```bash
cd robot && rsync -a --delete -e "ssh -i $HOME/.ssh/free-droid -o IdentitiesOnly=yes" \
  src/ creator@free-droid-001.home:/tmp/fd-src/
```

A Pi-n (a felhőnek és a `qwen3.5:4b`-nek futnia kell):

```bash
cd /opt/free-droid/robot && PYTHONPATH=/tmp/fd-src FREEDROID_VISION_ENABLED=igen \
  FREEDROID_VISION_MODEL=qwen3.5:4b uv run freedroid --debug 2>&1 | tee -a /tmp/szabi-$(date +%F-%H%M).log
```

- [ ] **Step 2: Az élő próbák**

1. „Nézz körül és mondd el, mit látsz." — a fej: közép → balra → jobbra → vissza középre; a válasz irányonként.
2. „Nézz fel és mondd el, mit látsz." — a fej felnéz, ott marad; a válasz a mennyezetről szól.
3. „Nézz balra, mit látsz?" — balra fordul, ott marad.
4. Letakart lencsével „Nézz körül!" — irányonként sötét, nem kitalált jelenet.
5. ÁLLJ a körbenézés közben — a fej a következő állomás előtt megáll.
6. A felhő lekapcsolva, „Nézz körül!" — a fej NEM mozdul, a robot mondja, hogy nem lát, nem esik safe módba.

- [ ] **Step 3: A napló ellenőrzése**

```bash
grep -E "látás: .* állomás|látás: ÁLLJ|látás kihagyva" /tmp/szabi-*.log | tail -20
ssh -i ~/.ssh/free-droid creator@free-droid-001.home 'sudo find /var/log/freedroid /tmp -name "*.jpg" -o -name "*.png"'
```

Expected: állomásonkénti időzítés; a `find` üres.

- [ ] **Step 4: Takarítás**

```bash
ssh -i ~/.ssh/free-droid creator@free-droid-001.home 'rm -rf /tmp/fd-src'
```

A transcript a debug posztúra része — a demó előtti törlés (`sudo find /var/log/freedroid/ -mindepth 1 -delete`) változatlanul érvényes.
