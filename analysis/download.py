"""Проверка и восстановление исходных данных: python -m analysis.download.

Значения размера и SHA256 сверены с data/metadata/dataset_research.json.
Загрузка идёт только с публичного endpoint Kaggle версии 1, без учётных данных.
Существующие несовпадающие файлы никогда не заменяются автоматически.
"""
from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from .config import ROOT

DATASET_PAGE = "https://www.kaggle.com/datasets/toobajamal/kdd99-dataset"
DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "toobajamal/kdd99-dataset?datasetVersionNumber=1"
)
ARCHIVE_NAME = "kdd99_kaggle.zip"
CSV_NAME = "kddcup99_csv.csv"
ARCHIVE_BYTES = 2_298_679
CSV_BYTES = 74_890_223
ARCHIVE_SHA256 = "a50c9ce5d83ac5d70e7d0ff986b3abf09a4412b7ca4b5edf63e3d52a850448e8"
CSV_SHA256 = "e411f3bb295d2be602f9288b333c15afee0f4cf85f7928916975d7b90b71917f"
CHUNK_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_SECONDS = 180


class DatasetDownloadError(RuntimeError):
    """Ошибка публичной загрузки, которую можно объяснить пользователю."""


class DatasetIntegrityError(DatasetDownloadError):
    """Файл не соответствует проверенному набору версии 1."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_existing(path: Path, size: int, expected_sha256: str) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise DatasetIntegrityError(f"Ожидался обычный файл: {path}")
    if path.stat().st_size != size or file_sha256(path) != expected_sha256:
        raise DatasetIntegrityError(
            f"Файл {path.name} не соответствует проверенной версии 1. "
            "Он сохранён без изменений. Переместите его в отдельную папку "
            "для проверки и повторите запуск; автоматической перезаписи нет."
        )
    return True


def _temporary_path(folder: Path, name: str) -> Path:
    descriptor, path = tempfile.mkstemp(prefix=f".{name}.", suffix=".part", dir=folder)
    os.close(descriptor)
    return Path(path)


def _atomic_install(temporary: Path, destination: Path, size: int, digest: str) -> bool:
    """Установить полностью проверенный файл, не перезаписывая даже при гонке."""
    if _verify_existing(destination, size, digest):
        return False
    try:
        if os.name == "nt":
            # В Windows rename атомарен и не заменяет уже существующий файл.
            os.rename(temporary, destination)
        else:
            # link создаёт имя атомарно и с запретом замены существующего файла.
            os.link(temporary, destination)
            temporary.unlink()
    except FileExistsError:
        _verify_existing(destination, size, digest)
        return False
    return True


def _manual_instructions(raw_dir: Path) -> str:
    return (
        f"Откройте {DATASET_PAGE} в браузере, при необходимости войдите "
        "в свою учётную запись Kaggle и скачайте набор кнопкой Download. "
        f"Сохраните исходный ZIP версии 1 как {raw_dir / ARCHIVE_NAME}, "
        "затем повторите python -m analysis.download. "
        "Программа проверит SHA256 и извлечёт CSV. "
        "API-ключи, токены и пароли в проект передавать не нужно."
    )


def _download_archive(raw_dir: Path) -> bool:
    destination = raw_dir / ARCHIVE_NAME
    temporary = _temporary_path(raw_dir, ARCHIVE_NAME)
    request = urllib.request.Request(
        DOWNLOAD_URL, headers={"User-Agent": "BigData-Bondarenko/1.0 public-data-download"}
    )
    started = time.monotonic()
    digest = hashlib.sha256()
    written = 0
    try:
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) != ARCHIVE_BYTES:
                    raise DatasetIntegrityError("Kaggle сообщил неожиданный размер архива версии 1.")
                with temporary.open("wb") as target:
                    while chunk := response.read(CHUNK_BYTES):
                        written += len(chunk)
                        if written > ARCHIVE_BYTES:
                            raise DatasetIntegrityError("Загрузка превышает проверенный размер ZIP.")
                        if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                            raise DatasetDownloadError("Истёк общий срок загрузки. Повторите запуск позже.")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise DatasetDownloadError(
                    f"Публичная загрузка Kaggle вернула HTTP {error.code}. "
                    + _manual_instructions(raw_dir)
                ) from error
            raise DatasetDownloadError(f"Kaggle вернул HTTP {error.code}. Повторите позже.") from error
        except (urllib.error.URLError, HTTPException, TimeoutError, OSError) as error:
            raise DatasetDownloadError(
                "Не удалось завершить публичную загрузку. Проверьте подключение. "
                + _manual_instructions(raw_dir)
            ) from error
        if written != ARCHIVE_BYTES or digest.hexdigest() != ARCHIVE_SHA256:
            raise DatasetIntegrityError("Размер или SHA256 скачанного ZIP не совпал с версией 1.")
        return _atomic_install(temporary, destination, ARCHIVE_BYTES, ARCHIVE_SHA256)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_archive(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    members = archive.infolist()
    if len(members) != 1:
        raise DatasetIntegrityError("В проверенном ZIP должен быть ровно один CSV-файл.")
    member = members[0]
    posix = PurePosixPath(member.filename)
    windows = PureWindowsPath(member.filename)
    if (
        posix.is_absolute() or windows.is_absolute() or windows.drive
        or ".." in posix.parts or ".." in windows.parts
        or member.filename != CSV_NAME or member.is_dir()
    ):
        raise DatasetIntegrityError("Недопустимый путь или имя файла в ZIP; извлечение остановлено.")
    if stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
        raise DatasetIntegrityError("Ссылки и зашифрованные элементы ZIP не поддерживаются.")
    if member.file_size != CSV_BYTES:
        raise DatasetIntegrityError("Распакованный размер CSV не соответствует проверенным данным.")
    return member


def _extract_csv(raw_dir: Path) -> bool:
    temporary = _temporary_path(raw_dir, CSV_NAME)
    destination = raw_dir / CSV_NAME
    written = 0
    digest = hashlib.sha256()
    try:
        try:
            with zipfile.ZipFile(raw_dir / ARCHIVE_NAME) as archive:
                member = _validate_archive(archive)
                with archive.open(member) as source, temporary.open("wb") as target:
                    while chunk := source.read(CHUNK_BYTES):
                        written += len(chunk)
                        if written > CSV_BYTES:
                            raise DatasetIntegrityError("Извлечение превышает проверенный размер CSV.")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
        except zipfile.BadZipFile as error:
            raise DatasetIntegrityError("Повреждён ZIP или контрольная сумма его содержимого.") from error
        if written != CSV_BYTES or digest.hexdigest() != CSV_SHA256:
            raise DatasetIntegrityError("Размер или SHA256 извлечённого CSV не совпал с версией 1.")
        return _atomic_install(temporary, destination, CSV_BYTES, CSV_SHA256)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_dataset(raw_dir: Path | None = None) -> dict:
    """Проверить имеющиеся raw; недостающие CSV восстановить из ZIP без сети."""
    folder = (Path(raw_dir) if raw_dir is not None else ROOT / "data/raw").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / ARCHIVE_NAME
    csv_path = folder / CSV_NAME
    archive_exists = _verify_existing(archive, ARCHIVE_BYTES, ARCHIVE_SHA256)
    csv_exists = _verify_existing(csv_path, CSV_BYTES, CSV_SHA256)
    downloaded = False
    extracted = False
    if not archive_exists:
        downloaded = _download_archive(folder)
    if not csv_exists:
        extracted = _extract_csv(folder)
    _verify_existing(archive, ARCHIVE_BYTES, ARCHIVE_SHA256)
    _verify_existing(csv_path, CSV_BYTES, CSV_SHA256)
    return {"archive": archive, "csv": csv_path, "downloaded": downloaded, "extracted": extracted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверить и восстановить исходный KDD99 версии 1.")
    parser.add_argument("--raw-dir", type=Path, help="Отдельная папка raw (по умолчанию data/raw проекта).")
    args = parser.parse_args(argv)
    try:
        result = ensure_dataset(args.raw_dir)
    except (DatasetDownloadError, OSError, ValueError) as error:
        print(f"Подготовка данных остановлена: {error}")
        return 1
    print("Исходные ZIP и CSV проверены по размеру и SHA256.")
    if result["downloaded"]:
        print("ZIP версии 1 скачан по публичной ссылке без учётных данных.")
    if result["extracted"]:
        print("Отсутствующий CSV восстановлен из проверенного ZIP.")
    print(f"CSV: {result['csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
