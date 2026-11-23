import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grayflag_dtc.paths import RES  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own data folder holding copies of the bundled datasets; nothing touches the repo's data/."""
    d = tmp_path / "data"
    shutil.copytree(RES / "data" / "theaters", d / "theaters")
    monkeypatch.setenv("GFDTC_DATA", str(d))
    monkeypatch.setenv("GFDTC_SAVED_GAMES", str(tmp_path / "no-saved-games"))
    monkeypatch.delenv("GFDTC_DCS_DIR", raising=False)
    return d
