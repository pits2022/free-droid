"""Unit tests for the <tool> parser (positional grammar).

parse_tools() is implemented (Phase 4.1 done for the parser), so these are live
guards — no xfail. Handlers wiring to hardware stays Phase 4 / @requires_pi.
"""

from __future__ import annotations

import pytest

from freedroid.tools.parser import ParsedTool, ToolParseError, parse_tools


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


# --- robustness: malformed/truncated model output (findings 1, 2, 4, 5, 6) --- #

# each row is a plausible small-model glitch that must NOT crash the parser.
MALFORMED = [
    "<tool></tool>",                       # empty (truncated)
    "<tool>scan_wifi filter</tool>",       # missing value
    "<tool>scan_wifi rescan now</tool>",   # invented key (injection surface)
    "<tool>set_speed</tool>",              # missing arg
    "<tool>set_mode</tool>",
    "<tool>set_oracle</tool>",
    "<tool>set_oracle true</tool>",        # not on/off (finding 5)
    "<tool>camera pan left</tool>",        # missing degrees
    "<tool>camera pan left sok</tool>",    # non-numeric degrees
    "<tool>camera pan up 45</tool>",       # pan can't go up (finding 4-ish)
    "<tool>move forward until</tool>",     # dangling until marker
    "<tool>turn balra 90</tool>",          # unknown (Hungarian) direction (finding 2)
    "<tool>move left 90</tool>",           # turn-word on move (finding 4)
    "<tool>turn forward 2</tool>",         # move-word on turn (finding 4)
]


@pytest.mark.parametrize("bad", MALFORMED)
def test_tolerant_drops_malformed_block_without_crashing(bad):
    assert parse_tools(bad) == []            # fail-closed: no call, no exception


@pytest.mark.parametrize("bad", MALFORMED)
def test_strict_raises_on_malformed_block(bad):
    with pytest.raises(ToolParseError):
        parse_tools(bad, strict=True)


def test_bad_block_does_not_lose_valid_siblings():
    # finding 1: one broken block must not drop the valid stop() next to it.
    out = parse_tools("Megyek! <tool></tool> <tool>stop</tool>")
    assert out == [ParsedTool("stop")]


def test_scan_wifi_reads_whitelisted_pairs():
    assert parse_tools("<tool>scan_wifi filter wpa3 sort signal</tool>") == [
        ParsedTool("scan_wifi", {"filter": "wpa3", "sort": "signal"})]


def test_camera_degrees_tolerates_float_like_turn():
    # finding 8: camera uses int(float(...)) just like turn, no ValueError.
    assert parse_tools("<tool>camera pan left 45.5</tool>") == [
        ParsedTool("camera", {"pan": "left", "degrees": 45})]
