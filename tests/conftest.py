import pytest

from extract import load, raw, upload


@pytest.fixture
def raw_root(tmp_path, monkeypatch):
    """Point the local raw store at a temporary folder, everywhere it's imported."""
    for module in (raw, load, upload):
        monkeypatch.setattr(module, "RAW_ROOT", tmp_path)
    return tmp_path
