"""Bound stalled and oversized package transfers without a real network request."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pinned_installer", ROOT / "scripts/install_dependencies.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def item():
    return {"name": "fixture", "version": "1", "filename": "fixture.whl", "url": "https://files.pythonhosted.org/fixture.whl", "sha256": hashlib.sha256(b"test").hexdigest(), "bytes": 4}


class Response:
    def __init__(self, payload=b"test"):
        self.payload = payload
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read1(self, size):
        self.reads += 1
        return self.payload if self.reads == 1 else b""


def test_installer_overall_file_timeout_prevents_infinite_trickling(monkeypatch, tmp_path):
    calls = []
    clock = [0]

    def monotonic():
        clock[0] += installer.MAX_DOWNLOAD_SECONDS + 1
        return clock[0]

    def open_response(url):
        response = Response()
        calls.append(response)
        return response

    monkeypatch.setattr(installer, "wheel_for", lambda pin, tags: item())
    monkeypatch.setattr(installer, "open_official", open_response)
    monkeypatch.setattr(installer, "time", SimpleNamespace(monotonic=monotonic, sleep=lambda _: None))
    with pytest.raises(TimeoutError, match="600 seconds"):
        installer.get_wheel(("fixture", "1"), set(), tmp_path)
    assert len(calls) == 3
    assert all(response.reads == 0 for response in calls)
    assert not (tmp_path / "fixture.whl").exists()


def test_installer_rejects_bytes_beyond_official_pypi_size(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "wheel_for", lambda pin, tags: item())
    monkeypatch.setattr(installer, "open_official", lambda url: Response(b"too many bytes"))
    monkeypatch.setattr(installer, "time", SimpleNamespace(monotonic=lambda: 0, sleep=lambda _: None))
    with pytest.raises(ValueError, match="exceeds"):
        installer.get_wheel(("fixture", "1"), set(), tmp_path)
    assert not (tmp_path / "fixture.whl").exists()
    assert (tmp_path / "fixture.whl.part").stat().st_size == 0
