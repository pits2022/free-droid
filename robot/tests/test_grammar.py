"""Contract tests binding the code's grammar (enums + ParsedTool) to the dataset.

These are the guard that catches drift: if a future dataset adds a tool value the
enums don't cover, these fail immediately.
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


def _values(name: str) -> set[str]:
    return {m.value for m in {
        "Direction": Direction, "TurnDir": TurnDir,
        "Speed": Speed, "Mode": Mode, "CameraAction": CameraAction,
    }[name]}


def test_every_dataset_tool_is_known(tool_calls):
    seen = {c["name"] for c in tool_calls}
    assert seen <= KNOWN_TOOLS, f"unknown tools in dataset: {seen - KNOWN_TOOLS}"


def test_move_direction_values_covered_by_enum(tool_calls):
    vals = {c["args"]["direction"] for c in tool_calls
            if c["name"] == "move" and "direction" in c["args"]}
    assert vals <= _values("Direction"), f"uncovered move directions: {vals}"


def test_turn_direction_values_covered_by_enum(tool_calls):
    vals = {c["args"]["direction"] for c in tool_calls
            if c["name"] == "turn" and "direction" in c["args"]}
    assert vals <= _values("TurnDir")


def test_speed_values_covered_by_enum(tool_calls):
    vals = {c["args"]["speed"] for c in tool_calls
            if c["name"] == "move" and "speed" in c["args"]}
    vals |= {c["args"]["level"] for c in tool_calls
             if c["name"] == "set_speed" and "level" in c["args"]}
    assert vals <= _values("Speed"), f"uncovered speeds: {vals}"


def test_mode_values_covered_by_enum(tool_calls):
    vals = {c["args"]["mode"] for c in tool_calls
            if c["name"] in ("move", "turn") and "mode" in c["args"]}
    assert vals <= _values("Mode"), f"uncovered modes: {vals}"


def test_camera_action_values_covered_by_enum(tool_calls):
    vals = {c["args"]["action"] for c in tool_calls
            if c["name"] == "camera" and "action" in c["args"]}
    assert vals <= _values("CameraAction")


def test_set_oracle_enabled_is_boolean(tool_calls):
    vals = {c["args"]["enabled"] for c in tool_calls
            if c["name"] == "set_oracle" and "enabled" in c["args"]}
    assert vals and vals <= {"true", "false"}


def test_dataset_uses_positional_args_somewhere(tool_calls):
    # set_mode("standby") — the reason ParsedTool must carry positional args.
    assert any(c["positional"] for c in tool_calls)


def test_parsedtool_holds_positional_and_keyword():
    t = ParsedTool("set_mode", positional=("standby",))
    assert t.name == "set_mode"
    assert t.positional == ("standby",)
    assert t.args == {}


def _dataset_modes(tool_calls) -> set[str]:
    modes = set()
    for c in tool_calls:
        if c["name"] in ("move", "turn") and "mode" in c["args"]:
            modes.add(c["args"]["mode"])
        if c["name"] == "set_mode":  # set_mode("standby") — positional
            modes.update(c["positional"])
            if "mode" in c["args"]:
                modes.add(c["args"]["mode"])
    return modes


# Reverse contract: every enum member is exercised by the dataset, so a dead or
# typo'd member is caught. (Speed.NORMAL is an intentional intermediate absent from
# the data, so Speed stays one-directional above.)
def test_direction_enum_has_no_dead_members(tool_calls):
    move_dirs = {c["args"]["direction"] for c in tool_calls
                 if c["name"] == "move" and "direction" in c["args"]}
    assert _values("Direction") == move_dirs


def test_turn_enum_has_no_dead_members(tool_calls):
    turn_dirs = {c["args"]["direction"] for c in tool_calls
                 if c["name"] == "turn" and "direction" in c["args"]}
    assert _values("TurnDir") == turn_dirs


def test_camera_action_enum_has_no_dead_members(tool_calls):
    actions = {c["args"]["action"] for c in tool_calls
               if c["name"] == "camera" and "action" in c["args"]}
    assert _values("CameraAction") == actions


def test_mode_enum_matches_dataset_including_positional(tool_calls):
    assert _values("Mode") == _dataset_modes(tool_calls)


def test_set_mode_positional_values_are_valid_modes(tool_calls):
    positional_modes = {v for c in tool_calls if c["name"] == "set_mode" for v in c["positional"]}
    assert positional_modes  # the dataset really does use set_mode(...) positionally
    assert positional_modes <= _values("Mode")
