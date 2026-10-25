"""Проверки загрузчика без изменения data/raw проекта и без внешней сети."""
from __future__ import annotations
import hashlib
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from analysis import download as dl


class FakeResponse(io.BytesIO):
    def __init__(self, content, declared=None):
        super().__init__(content)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = dl.ROOT / "data/raw" / dl.ARCHIVE_NAME
        cls.archive = cls.fixture.read_bytes()
        assert len(cls.archive) == dl.ARCHIVE_BYTES
        assert hashlib.sha256(cls.archive).hexdigest() == dl.ARCHIVE_SHA256

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bigdata_download_test_")
        self.raw = Path(self.temporary.name)
        self.assertEqual(self.raw.parent.resolve(), Path(tempfile.gettempdir()).resolve())

    def tearDown(self):
        # TemporaryDirectory owns only its verified newly created folder.
        self.temporary.cleanup()

    def assert_no_partial_files(self):
        self.assertEqual(list(self.raw.glob("*.part")), [])

    def test_constants_match_verified_packaged_metadata(self):
        data = json.loads((dl.ROOT / "data/metadata/dataset_research.json").read_text(encoding="utf-8"))
        self.assertEqual(data["files"]["zip"]["sha256"], dl.ARCHIVE_SHA256)
        self.assertEqual(data["files"]["csv"]["sha256"], dl.CSV_SHA256)
        self.assertEqual(data["files"]["zip"]["bytes"], dl.ARCHIVE_BYTES)
        self.assertEqual(data["files"]["csv"]["bytes"], dl.CSV_BYTES)
        self.assertEqual(data["download"]["version_pinned_url"]["url"], dl.DOWNLOAD_URL)

    def test_missing_csv_recovers_locally_without_network(self):
        shutil.copyfile(self.fixture, self.raw / dl.ARCHIVE_NAME)
        with patch.object(dl.urllib.request, "urlopen", side_effect=AssertionError("Сеть запрещена тестом")):
            result = dl.ensure_dataset(self.raw)
            second = dl.ensure_dataset(self.raw)
        self.assertFalse(result["downloaded"])
        self.assertTrue(result["extracted"])
        self.assertFalse(second["downloaded"])
        self.assertFalse(second["extracted"])
        self.assertEqual(dl.file_sha256(self.raw / dl.CSV_NAME), dl.CSV_SHA256)
        self.assert_no_partial_files()

    def test_missing_both_uses_public_pinned_request(self):
        with patch.object(dl.urllib.request, "urlopen", return_value=FakeResponse(self.archive, dl.ARCHIVE_BYTES)) as request:
            result = dl.ensure_dataset(self.raw)
        self.assertTrue(result["downloaded"])
        self.assertTrue(result["extracted"])
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, dl.DOWNLOAD_URL)
        headers = {k.lower(): v for k, v in sent.header_items()}
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)
        self.assertEqual(request.call_args.kwargs["timeout"], dl.REQUEST_TIMEOUT_SECONDS)
        self.assert_no_partial_files()

    def test_changed_csv_is_preserved_and_network_not_used(self):
        shutil.copyfile(self.fixture, self.raw / dl.ARCHIVE_NAME)
        target = self.raw / dl.CSV_NAME
        target.write_bytes(b"user data; keep unchanged")
        with patch.object(dl.urllib.request, "urlopen", side_effect=AssertionError("Сеть запрещена тестом")):
            with self.assertRaises(dl.DatasetIntegrityError):
                dl.ensure_dataset(self.raw)
        self.assertEqual(target.read_bytes(), b"user data; keep unchanged")
        self.assert_no_partial_files()

    def test_changed_archive_is_preserved(self):
        target = self.raw / dl.ARCHIVE_NAME
        target.write_bytes(b"user archive")
        with self.assertRaises(dl.DatasetIntegrityError):
            dl.ensure_dataset(self.raw)
        self.assertEqual(target.read_bytes(), b"user archive")
        self.assertFalse((self.raw / dl.CSV_NAME).exists())

    def test_401_and_403_have_concrete_manual_instructions(self):
        for status in (401, 403):
            with self.subTest(status=status):
                error = urllib.error.HTTPError(dl.DOWNLOAD_URL, status, "denied", {}, None)
                with patch.object(dl.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(dl.DatasetDownloadError) as caught:
                        dl.ensure_dataset(self.raw)
                message = str(caught.exception)
                self.assertIn(dl.DATASET_PAGE, message)
                self.assertIn(str(self.raw / dl.ARCHIVE_NAME), message)
                self.assertIn("Download", message)
                self.assertFalse((self.raw / dl.ARCHIVE_NAME).exists())
                self.assert_no_partial_files()

    def test_download_size_limit_removes_partial_file(self):
        with patch.object(dl.urllib.request, "urlopen", return_value=FakeResponse(b"x", dl.ARCHIVE_BYTES + 1)):
            with self.assertRaises(dl.DatasetIntegrityError):
                dl.ensure_dataset(self.raw)
        self.assertFalse((self.raw / dl.ARCHIVE_NAME).exists())
        self.assert_no_partial_files()

    def test_download_hash_mismatch_removes_partial_file(self):
        with patch.object(dl.urllib.request, "urlopen", return_value=FakeResponse(b"x" * dl.ARCHIVE_BYTES)):
            with self.assertRaises(dl.DatasetIntegrityError):
                dl.ensure_dataset(self.raw)
        self.assertFalse((self.raw / dl.ARCHIVE_NAME).exists())
        self.assert_no_partial_files()

    def test_stream_overrun_is_bounded(self):
        with patch.object(dl.urllib.request, "urlopen", return_value=FakeResponse(b"x" * (dl.ARCHIVE_BYTES + 1))):
            with self.assertRaises(dl.DatasetIntegrityError):
                dl.ensure_dataset(self.raw)
        self.assert_no_partial_files()

    def test_interrupted_stream_removes_partial_download(self):
        response = FakeResponse(self.archive)
        response.read = unittest.mock.Mock(side_effect=IncompleteRead(b"partial"))
        with patch.object(dl.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(dl.DatasetDownloadError):
                dl.ensure_dataset(self.raw)
        self.assertFalse((self.raw / dl.ARCHIVE_NAME).exists())
        self.assert_no_partial_files()

    def test_total_download_timeout_removes_partial_download(self):
        with patch.object(dl.urllib.request, "urlopen", return_value=FakeResponse(self.archive)):
            with patch.object(dl.time, "monotonic", side_effect=[0, dl.MAX_DOWNLOAD_SECONDS + 1]):
                with self.assertRaises(dl.DatasetDownloadError):
                    dl.ensure_dataset(self.raw)
        self.assertFalse((self.raw / dl.ARCHIVE_NAME).exists())
        self.assert_no_partial_files()

    def test_archive_paths_extra_members_and_declared_size_rejected(self):
        for entries in (
            [("../" + dl.CSV_NAME, b"x")],
            [("C:/" + dl.CSV_NAME, b"x")],
            [("/" + dl.CSV_NAME, b"x")],
            [(dl.CSV_NAME, b"x"), ("extra.txt", b"x")],
            [(dl.CSV_NAME, b"x")],
        ):
            with self.subTest(names=[name for name, _ in entries]):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    for name, content in entries:
                        archive.writestr(name, content)
                with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
                    with self.assertRaises(dl.DatasetIntegrityError):
                        dl._validate_archive(archive)

    def test_extracted_content_hash_checked_before_install(self):
        with zipfile.ZipFile(self.raw / dl.ARCHIVE_NAME, "w") as archive:
            archive.writestr(dl.CSV_NAME, b"bad")
        with patch.object(dl, "CSV_BYTES", 3):
            with self.assertRaises(dl.DatasetIntegrityError):
                dl._extract_csv(self.raw)
        self.assertFalse((self.raw / dl.CSV_NAME).exists())
        self.assert_no_partial_files()

    def test_cli_returns_failure_for_incompatible_raw(self):
        (self.raw / dl.ARCHIVE_NAME).write_bytes(b"wrong")
        self.assertEqual(dl.main(["--raw-dir", str(self.raw)]), 1)


if __name__ == "__main__":
    unittest.main()
