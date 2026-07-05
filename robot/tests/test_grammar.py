"""Contract tests binding the code's grammar (enums + parser) to the dataset.

The `tool_calls` fixture parses every dataset <tool> call through the real
parse_tools(), so these tests validate the *parsed* values against the enums.
If a future dataset adds a tool value the enums don't cover — or the parser
mis-maps a token — these fail immediately.
"""

from __future__ import annotations

from freedroid.camera import CameraAction
from freedroid.motion.types import Direction, Mode, Speed, TurnDir
from freedroid.tools.parser import ParsedTool

KNOWN_TOOLS = {
    "move", "turn", "stop", "camera",
    "set_speed", "set_mode", "request_navigation_help", "scan_wifi",
    "set_oracle",  # optional "Tudók" routing toggle (default off / sovereign)
}

# camera pan/tilt directions — not enums (camera-local); a small fixed set.
_PAN = {"left", "right"}
_TILT = {"up", "down"}


def _vals(enum) -> set[str]:
    return {m.value for m in enum}


def test_every_dataset_tool_is_known(tool_calls):
    seen = {c.name for c in tool_calls}
    assert seen <= KNOWN_TOOLS, f"unknown tools in dataset: {seen - KNOWN_TOOLS}"


def test_move_directions_match_enum(tool_calls):
    vals = {c.args["direction"] for c in tool_calls
            if c.name == "move" and "direction" in c.args}
    assert vals == _vals(Direction), f"move directions vs enum: {vals}"


def test_turn_directions_match_enum(tool_calls):
    vals = {c.args["direction"] for c in tool_calls
            if c.name == "turn" and "direction" in c.args}
    assert vals == _vals(TurnDir), f"turn directions vs enum: {vals}"


def test_speeds_subset_of_enum(tool_calls):
    vals = {c.args["speed"] for c in tool_calls
            if c.name == "move" and "speed" in c.args}
    vals |= {c.args["level"] for c in tool_calls
             if c.name == "set_speed" and "level" in c.args}
    # Speed.NORMAL may be an intentional intermediate not always in the data.
    assert vals <= _vals(Speed), f"uncovered speeds: {vals - _vals(Speed)}"


def test_modes_match_enum(tool_calls):
    # move/turn mode + set_mode mode — every Mode member exercised, none unknown.
    vals = {c.args["mode"] for c in tool_calls if "mode" in c.args}
    assert vals == _vals(Mode), f"modes vs enum: {vals}"


def test_camera_actions_match_enum(tool_calls):
    vals = {c.args["action"] for c in tool_calls
            if c.name == "camera" and "action" in c.args}
    assert vals == _vals(CameraAction), f"camera actions vs enum: {vals}"


def test_camera_pan_tilt_directions_valid(tool_calls):
    pans = {c.args["pan"] for c in tool_calls if c.name == "camera" and "pan" in c.args}
    tilts = {c.args["tilt"] for c in tool_calls if c.name == "camera" and "tilt" in c.args}
    assert pans <= _PAN, f"bad pan: {pans - _PAN}"
    assert tilts <= _TILT, f"bad tilt: {tilts - _TILT}"


def test_until_values_are_obstacle(tool_calls):
    vals = {c.args["until"] for c in tool_calls if "until" in c.args}
    assert vals <= {"obstacle"}, f"unexpected until: {vals}"


def test_set_oracle_enabled_is_bool(tool_calls):
    vals = {c.args["enabled"] for c in tool_calls
            if c.name == "set_oracle" and "enabled" in c.args}
    assert vals == {True, False}, f"set_oracle enabled not bool pair: {vals}"


def test_numeric_args_are_typed(tool_calls):
    # move distance -> float, turn/camera degrees -> int (parser coercion contract).
    for c in tool_calls:
        if c.name == "move" and "distance" in c.args:
            assert isinstance(c.args["distance"], float)
        if "degrees" in c.args:
            assert isinstance(c.args["degrees"], int)


def test_parsedtool_construction():
    t = ParsedTool("set_mode", {"mode": "standby"})
    assert t.name == "set_mode"
    assert t.args == {"mode": "standby"}
