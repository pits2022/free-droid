"""TDD harness for the <tool> parser (Phase 4.1).

These describe the intended behaviour of parse_tools(). They xfail (strict) until
it is implemented; the moment it works, xfail flips to XPASS and forces removing
the marker — turning each spec into a live guard.
"""

from __future__ import annotations

import pytest

from freedroid.tools.parser import ParsedTool, parse_tools

pytestmark = pytest.mark.phase4


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_single_keyword_call():
    out = parse_tools('<tool>move(direction="forward", distance=2.0)</tool>')
    assert out == [ParsedTool("move", {"direction": "forward", "distance": 2.0})]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_no_arg_call():
    assert parse_tools("<tool>stop()</tool>") == [ParsedTool("stop")]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_positional_arg():
    assert parse_tools('<tool>set_mode("standby")</tool>') == [
        ParsedTool("set_mode", positional=("standby",))
    ]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_mode_only_move():
    assert parse_tools('<tool>move(mode="approach_speaker")</tool>') == [
        ParsedTool("move", {"mode": "approach_speaker"})
    ]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_multiple_calls_in_one_response():
    out = parse_tools('Megyek! <tool>turn(direction="left", degrees=90)</tool> '
                      'aztán <tool>stop()</tool>')
    assert [t.name for t in out] == ["turn", "stop"]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_tolerates_whitespace_and_ignores_prose():
    assert parse_tools("no tools here") == []
    out = parse_tools("<tool>  stop( ) </tool>")
    assert out == [ParsedTool("stop")]


@pytest.mark.xfail(reason="Phase 4.1: parse_tools not implemented", strict=True)
def test_parses_every_real_dataset_call(tool_calls):
    # Exact: the parser must reproduce every dataset call with numeric coercion
    # ("2.0"->2.0 float, "90"->90 int) and not drop/duplicate args.
    for call in tool_calls:
        expected = ParsedTool(
            call["name"],
            {k: _coerce(v) for k, v in call["args"].items()},
            tuple(_coerce(v) for v in call["positional"]),
        )
        out = parse_tools(f"<tool>{_render(call)}</tool>")
        assert out == [expected]


def _render(call: dict) -> str:
    parts = [f'{k}="{v}"' if not _is_num(v) else f"{k}={v}"
             for k, v in call["args"].items()]
    parts += [f'"{v}"' for v in call["positional"]]
    return f"{call['name']}({', '.join(parts)})"


def _coerce(v: str):
    if not _is_num(v):
        return v
    return float(v) if "." in v else int(v)


def _is_num(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
