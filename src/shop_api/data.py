"""Loads test design tables from ``data/`` into readable pytest parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load(relative: str) -> dict[str, Any]:
    with (DATA_DIR / relative).open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict):
        raise TypeError(f"{relative} must contain a mapping")
    return doc


def cases(relative: str, group: str) -> list[Any]:
    """``pytest.param`` per case with the case id; cases with ``finding`` become strict xfails."""
    table = load(relative)[group]
    params = []
    for case in table["cases"]:
        marks = []
        if finding := case.get("finding"):
            marks.append(pytest.mark.xfail(reason=f"{finding}: documented in docs/findings.md", strict=True))
            marks.append(pytest.mark.finding(finding))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


def technique(relative: str, group: str) -> str:
    return str(load(relative)[group]["technique"])
