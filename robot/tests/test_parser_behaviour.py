"""Unit tests for the <tool> parser (positional grammar).

parse_tools() is implemented (Phase 4.1 done for the parser), so these are live
guards — no xfail. Handlers wiring to hardware stays Phase 4 / @requires_pi.
"""

from __future__ import annotations

from freedroid.tools.parser import ParsedTool, parse_tools


def test_parses_single_call_with_distance():
    assert parse_tools("<tool>move forward 2</tool>") == [
        ParsedTool("move", {"direction": "forward", "distance": 2.0})
    ]


def test_distance_is_float_degrees_is_int():
    dist = parse_tools("<tool>move forward 2</tool>")[0].args["distance"]
    deg = parse_tools("<tool>turn left 90</tool>")[0].args["degrees"]
    assert dist == 2.0 and isinstance(dist, float)
    assert deg == 90 and isinstance(deg, int)


def test_parses_no_arg_call():
    assert parse_tools("<tool>stop</tool>") == [ParsedTool("stop")]


def test_parses_speed_and_mode_only_move():
    assert parse_tools("<tool>move forward slow</tool>") == [
        ParsedTool("move", {"direction": "forward", "speed": "slow"})]
    assert parse_tools("<tool>move approach_speaker</tool>") == [
        ParsedTool("move", {"mode": "approach_speaker"})]


def test_parses_until_marker():
    assert parse_tools("<tool>move forward until obstacle</tool>") == [
        ParsedTool("move", {"direction": "forward", "until": "obstacle"})]


def test_parses_camera_pan_and_action():
    assert parse_tools("<tool>camera scan</tool>") == [
        ParsedTool("camera", {"action": "scan"})]
    assert parse_tools("<tool>camera pan left 45</tool>") == [
        ParsedTool("camera", {"pan": "left", "degrees": 45})]


def test_set_oracle_is_bool():
    assert parse_tools("<tool>set_oracle off</tool>")[0].args["enabled"] is False
    assert parse_tools("<tool>set_oracle on</tool>")[0].args["enabled"] is True


def test_free_text_target_keeps_spaces():
    assert parse_tools("<tool>request_navigation_help piros szék</tool>") == [
        ParsedTool("request_navigation_help", {"target": "piros szék"})]


def test_parses_multiple_calls_in_one_response():
    out = parse_tools("Megyek! <tool>turn left 90</tool> aztán <tool>stop</tool>")
    assert [t.name for t in out] == ["turn", "stop"]


def test_tolerates_whitespace_and_ignores_prose():
    assert parse_tools("no tools here") == []
    assert parse_tools("<tool>  stop </tool>") == [ParsedTool("stop")]
