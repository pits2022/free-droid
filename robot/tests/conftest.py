"""Shared fixtures and helpers for the freedroid test suite."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from freedroid.config.settings import Settings, load_settings
from freedroid.health.probe import is_pi

IS_PI = is_pi()

# repo root: robot/tests/conftest.py -> parents[2]
_DATASET = Path(__file__).resolve().parents[2] / "training" / "dataset" / "freedroid_full.json"

_TOOL_RE = re.compile(r"<tool>(.*?)</tool>", re.S)
_CALL_RE = re.compile(r"^\s*([a-z_]+)\s*\((.*)\)\s*$", re.S)


def _parse_arg(arg: str):
    """('key', value) for key=value, or (None, value) for a positional arg."""
    arg = arg.strip()
    if "=" in arg:
        k, v = arg.split("=", 1)
        return k.strip(), v.strip().strip('"')
    return None, arg.strip().strip('"')


def load_tool_calls() -> list[dict]:
    """Every <tool> call in the dataset as {name, args: {k: v}, positional: [v]}."""
    calls = []
    for ex in json.loads(_DATASET.read_text()):
        for raw in _TOOL_RE.findall(ex.get("output", "")):
            m = _CALL_RE.match(raw.strip())
            if not m:
                continue
            name, inside = m.group(1), m.group(2).strip()
            args, positional = {}, []
            if inside:
                for part in inside.split(","):
                    key, val = _parse_arg(part)
                    if key is None:
                        positional.append(val)
                    else:
                        args[key] = val
            calls.append({"name": name, "args": args, "positional": positional})
    return calls


@pytest.fixture(scope="session")
def tool_calls() -> list[dict]:
    return load_tool_calls()


@pytest.fixture
def settings() -> Settings:
    return load_settings()


requires_pi = pytest.mark.skipif(not IS_PI, reason="requires real Raspberry Pi hardware")
