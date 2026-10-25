r"""Install the pinned Windows environment using official PyPI JSON + wheels.

The alternate download path avoids a slow /simple/ index on some machines.
Run with .venv\Scripts\python.exe; neither system Python nor other projects change.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {"pypi.org", "files.pythonhosted.org"}
MAX_DOWNLOAD_SECONDS = 600


def checked_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Dependency download URL is not an allowed official PyPI HTTPS URL")
    return url


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


OPENER = urllib.request.build_opener(OfficialRedirects())


def open_official(url: str):
    request = urllib.request.Request(checked_url(url), headers={"User-Agent": "BigData-Bondarenko-dependency-setup/1.0"})
    return OPENER.open(request, timeout=30)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def pins() -> list[tuple[str, str]]:
    result = []
    for text in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        text = text.strip()
        if not text or text.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", text):
            raise ValueError("requirements-lock.txt must contain only fixed package==version pins")
        name, version = text.split("==", 1)
        result.append((name, version))
    if not result:
        raise ValueError("The dependency lock is empty")
    return result


def wheel_for(pin: tuple[str, str], tags: set) -> dict:
    name, version = pin
    url = f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/{urllib.parse.quote(version, safe='')}/json"
    for attempt in range(3):
        try:
            with open_official(url) as response:
                metadata = json.load(response)
            break
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)
    for entry in metadata["urls"]:
        filename = entry["filename"]
        if entry.get("yanked") or not filename.endswith(".whl"):
            continue
        try:
            _, _, _, wheel_tags = parse_wheel_filename(filename)
        except ValueError:
            continue
        if wheel_tags & tags:
            checked_url(entry["url"])
            return {"name": name, "version": version, "filename": filename, "url": entry["url"], "sha256": entry["digests"]["sha256"], "bytes": entry["size"]}
    raise RuntimeError(f"No compatible wheel for {name}=={version}. Use Windows x64 and Python 3.12.")


def get_wheel(pin: tuple[str, str], tags: set, cache: Path) -> dict:
    item = wheel_for(pin, tags)
    path = cache / item["filename"]
    if path.exists() and digest(path) == item["sha256"]:
        print(f"Verified cache: {item['filename']}", flush=True)
        return {**item, "path": str(path)}
    partial = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            print(f"Downloading {item['filename']}...", flush=True)
            started = time.monotonic()
            received = 0
            with open_official(item["url"]) as response, partial.open("wb") as stream:
                while True:
                    if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                        raise TimeoutError(f"Package download exceeded {MAX_DOWNLOAD_SECONDS} seconds: " + item["filename"])
                    # read1 returns currently available bytes instead of waiting
                    # to fill a large buffer during a stalled/trickling response.
                    block = response.read1(64 * 1024)
                    if not block:
                        break
                    received += len(block)
                    if received > item["bytes"]:
                        raise ValueError("Download exceeds the declared PyPI wheel size")
                    stream.write(block)
            if received != item["bytes"]:
                raise ValueError("Incomplete package download: " + item["filename"])
            if digest(partial) != item["sha256"]:
                raise ValueError("SHA-256 does not match PyPI metadata: " + item["filename"])
            partial.replace(path)
            print(f"Verified download: {item['filename']}", flush=True)
            return {**item, "path": str(path)}
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".dependency_cache/wheels")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    expected_prefix = (ROOT / ".venv").resolve()
    if Path(sys.prefix).resolve() != expected_prefix or sys.prefix == sys.base_prefix:
        raise SystemExit("Run this installer with this project's .venv\\Scripts\\python.exe")
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise SystemExit("This tested dependency lock requires 64-bit Python 3.12.")
    cache = args.cache_dir.resolve()
    if not cache.is_relative_to(ROOT):
        raise SystemExit("The dependency cache must stay inside this project directory")
    cache.mkdir(parents=True, exist_ok=True)
    tags = set(sys_tags())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        wheels = list(pool.map(lambda pin: get_wheel(pin, tags, cache), pins()))
    record = {"python": sys.version, "executable": sys.executable, "source": "Official PyPI JSON API; HTTPS host allowlist; SHA-256 checked", "wheels": wheels}
    (cache.parent / "installation_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.download_only:
        return
    command = [sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(cache), "-r", str(ROOT / "requirements-lock.txt")]
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "pip", "check"], cwd=ROOT, check=True)
    print("Pinned dependencies installed and checked successfully.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Dependency installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
