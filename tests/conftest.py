"""Shared fixtures. Every test runs with DROIDFORGE_HOME in a temp dir (never the real home)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def df_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "dfhome"
    monkeypatch.setenv("DROIDFORGE_HOME", str(home))
    return home
