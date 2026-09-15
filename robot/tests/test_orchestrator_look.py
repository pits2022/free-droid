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
    settings = dataclasses.replace(Settings(), vision=VisionSettings(
        enabled=True, model="fake-vlm:latest", **vision))
    cam = FakeCamera(rec) if camera == "fake" else camera
    o = Orchestrator(settings=settings, llm=PromptLLM(), vlm=vlm, camera=cam,
                     motion=Stub(), watchdog=Stub())
    monkeypatch.setattr("freedroid.orchestrator.transcript.log", lambda *a, **k: None)
    monkeypatch.setattr(o, "_talalatok", lambda k: [])
    monkeypatch.setattr(o, "_settle", sleeps.append)
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


def test_stop_event_during_the_last_station_skips_the_return_to_centre(monkeypatch):
    """A reviewer-mérte eset: az ÁLLJ a HARMADIK (utolsó) állomás describe-ja alatt jön.
    A for-ciklus ilyenkor RENDESEN kifut (nincs `break`), tehát egy, csak a ciklus
    TETEJÉN olvasott jelző nem venné észre — a záró vissza-középrének az ÉLŐ eseményt
    kell néznie, nem egy befagyasztott `stopped` változót."""
    rec = Recorder()
    stop = threading.Event()

    class LastStationStoppingVLM(FakeVLM):
        def describe(self, jpeg):
            eredmeny = super().describe(jpeg)
            if not self.answers:            # ez volt az UTOLSÓ állomás leírása
                stop.set()
            return eredmeny

    o, _ = build(monkeypatch, rec,
                LastStationStoppingVLM(rec, ["egy ajtó", "egy ablak", "egy polc"]))
    o._stop_event = stop
    o.ask("Nézz körül!")
    assert [e[0] for e in rec.events] == [
        "move_to", "grab", "describe", "move_to", "grab", "describe", "move_to", "grab", "describe",
    ], "ÁLLJ az utolsó leírás alatt: nincs záró vissza-középre move_to"


def test_stop_event_during_settle_skips_the_frame_of_that_station(monkeypatch):
    """A `_settle()` reagál az ÁLLJ-ra és visszatér — de enélkül a fix nélkül a HÍVÓ
    (`_look`) ezt nem nézte volna meg: a MOZDULT állomás képét a VLM-nek elküldte volna
    (akár 9,6 s felesleges hálózati munka egy eredményért, amit `_egy_kor` úgyis eldob),
    és a hurok süket maradt volna a KÖVETKEZŐ gombnyomásra. Az ÁLLJ-t a settle UTÁN
    AZONNAL ellenőrizni kell, mielőtt a képkocka-lekérés elindulna."""
    rec = Recorder()
    stop = threading.Event()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó"]))
    o._stop_event = stop
    # A "Balra" állomás mozdulna (az induló póz (0,0), a "Balra" (45,0)) — ez a settle,
    # ami itt az ÁLLJ-t állítja be, mintha a gomb épp a beállás alatt nyomódott volna.
    monkeypatch.setattr(o, "_settle", lambda seconds: stop.set())

    o.ask("Nézz körül!")

    kinds = [e[0] for e in rec.events]
    assert kinds == ["move_to", "grab", "describe", "move_to"], (
        "az Előre állomás (nem mozdul) lefut, a Balra CSAK a move_to-ig jut — "
        "grab/describe nem indul, és a Jobbra + a záró vissza-középre sem")
    assert sum(1 for e in rec.events if e[0] == "describe") == 1
    assert rec.events[-1] == ("move_to", 45.0, 0.0), "nincs záró vissza-középre"


def test_settle_is_interruptible_by_the_stop_event(monkeypatch):
    """`stop_event.wait(settle_s)`, nem `sleep` — az ÁLLJ a beállás alatt se várjon."""
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, []))
    monkeypatch.undo()   # a valódi _settle kell
    stop = threading.Event()
    stop.set()
    o._stop_event = stop
    import time as _time
    started = _time.monotonic()
    Orchestrator._settle(o, 2.0)
    assert _time.monotonic() - started < 0.5


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


def test_vlm_exception_keeps_earlier_lines_and_recentres(monkeypatch):
    """PR #137 review: egy VLM-kivétel a 2. állomáson ne dobja el az 1. leírását, és ne
    hagyja a fejet kitekerve."""
    rec = Recorder()

    class RaisingVLM(FakeVLM):
        def describe(self, jpeg):
            if len(self.answers) == 2:          # a 2. hívás
                rec.events.append(("describe", jpeg))
                raise TimeoutError("VLM")
            return super().describe(jpeg)

    o, _ = build(monkeypatch, rec, RaisingVLM(rec, ["egy ajtó", "soha", "soha"]))
    o.ask("Nézz körül!")
    assert "Előre: egy ajtó" in o.llm.prompts[0]
    assert "Balra:" not in o.llm.prompts[0]
    assert rec.events[-1] == ("move_to", 0.0, 0.0), "kivétel után is vissza középre"


def test_grab_exception_is_a_missing_frame_and_the_tour_goes_on(monkeypatch):
    rec = Recorder()
    o, _ = build(monkeypatch, rec, FakeVLM(rec, ["egy ajtó", "egy polc"]))
    frames = iter([b"f1", RuntimeError("cv2"), b"f3"])

    def grab(*a, **kw):
        item = next(frames)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg", grab)
    o.ask("Nézz körül!")
    assert "Előre: egy ajtó\nBalra: nem adott képet a kamera.\nJobbra: egy polc" in o.llm.prompts[0]
