import pytest

from ballmonitor.models.race_podium import ingest


@pytest.fixture(autouse=True)
def _scratch_races_db(tmp_path, monkeypatch):
    """Keep tests from writing parsed results into the committed data/races.db cache."""
    monkeypatch.setattr(ingest, "DEFAULT_DB", tmp_path / "races.db")
