from __future__ import annotations

import hashlib
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from gdelt_world.schemas import inspect_zip

GDELT_HTTPS_ROOT = "https://data.gdeltproject.org/gdeltv2"
GDELT_HTTP_ROOT = "http://data.gdeltproject.org/gdeltv2"
BATCH_PATTERN = re.compile(r"/(\d{14})\.(export\.CSV|mentions\.CSV|gkg\.csv)\.zip$")
KIND_BY_SUFFIX = {
    "export.CSV": "events",
    "mentions.CSV": "mentions",
    "gkg.csv": "gkg",
}


@dataclass(frozen=True)
class ManifestEntry:
    size_bytes: int
    md5: str
    url: str
    batch_id: str
    kind: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FetchAttempt:
    url: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class ManifestResult:
    source_url: str
    entries: tuple[ManifestEntry, ...]
    attempts: tuple[FetchAttempt, ...]
    insecure_transport: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "entries": [entry.to_dict() for entry in self.entries],
            "attempts": [asdict(attempt) for attempt in self.attempts],
            "insecure_transport": self.insecure_transport,
        }


@dataclass(frozen=True)
class DownloadResult:
    entry: ManifestEntry
    path: str
    size_bytes: int
    md5: str
    sha256: str
    inspection: dict[str, object]
    reused: bool

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["entry"] = self.entry.to_dict()
        return result


def parse_manifest(text: str) -> tuple[ManifestEntry, ...]:
    entries: list[ManifestEntry] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"manifest line {line_number}: expected 3 fields, got {len(parts)}")
        size_raw, md5, url = parts
        match = BATCH_PATTERN.search(url)
        if not match:
            raise ValueError(f"manifest line {line_number}: unsupported GDELT URL {url!r}")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
            raise ValueError(f"manifest line {line_number}: invalid MD5 {md5!r}")
        entries.append(
            ManifestEntry(
                size_bytes=int(size_raw),
                md5=md5.lower(),
                url=url,
                batch_id=match.group(1),
                kind=KIND_BY_SUFFIX[match.group(2)],
            )
        )
    if not entries:
        raise ValueError("manifest is empty")
    return tuple(entries)


def _get_bytes(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hello-gdelt/0.1 (+local research validator)", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_lastupdate(*, timeout: float = 30, allow_http_fallback: bool = False) -> ManifestResult:
    urls = [f"{GDELT_HTTPS_ROOT}/lastupdate.txt"]
    if allow_http_fallback:
        urls.append(f"{GDELT_HTTP_ROOT}/lastupdate.txt")

    attempts: list[FetchAttempt] = []
    for url in urls:
        try:
            text = _get_bytes(url, timeout=timeout).decode("utf-8")
            entries = parse_manifest(text)
            attempts.append(FetchAttempt(url=url, ok=True))
            return ManifestResult(
                source_url=url,
                entries=entries,
                attempts=tuple(attempts),
                insecure_transport=urlparse(url).scheme != "https",
            )
        except (OSError, UnicodeError, ValueError) as exc:
            attempts.append(FetchAttempt(url=url, ok=False, error=f"{type(exc).__name__}: {exc}"))
    detail = "; ".join(f"{item.url}: {item.error}" for item in attempts)
    raise RuntimeError(f"all lastupdate endpoints failed: {detail}")


def fetch_masterfile_tail(
    *,
    root: str,
    tail_bytes: int = 300_000,
    timeout: float = 60,
) -> tuple[ManifestEntry, ...]:
    url = f"{root.rstrip('/')}/masterfilelist.txt"
    head = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "hello-gdelt/0.1 (+local research validator)"},
    )
    with urllib.request.urlopen(head, timeout=timeout) as response:
        length_raw = response.headers.get("Content-Length")
    if not length_raw:
        raise RuntimeError("masterfilelist HEAD response has no Content-Length")
    length = int(length_raw)
    start = max(0, length - tail_bytes)
    data = _get_bytes(url, timeout=timeout, headers={"Range": f"bytes={start}-{length - 1}"})
    text = data.decode("utf-8", errors="strict")
    if start > 0 and "\n" in text:
        text = text.split("\n", 1)[1]
    return parse_manifest(text)


def group_complete_batches(
    entries: Iterable[ManifestEntry],
) -> list[tuple[str, tuple[ManifestEntry, ...]]]:
    grouped: dict[str, dict[str, ManifestEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.batch_id, {})[entry.kind] = entry
    required = {"events", "mentions", "gkg"}
    complete = [
        (batch, tuple(by_kind[kind] for kind in ("events", "mentions", "gkg")))
        for batch, by_kind in grouped.items()
        if required.issubset(by_kind)
    ]
    return sorted(complete, key=lambda item: item[0], reverse=True)


def file_md5(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_download(entry: ManifestEntry, path: Path) -> dict[str, object]:
    size = path.stat().st_size
    if size != entry.size_bytes:
        raise ValueError(f"size mismatch for {path.name}: expected {entry.size_bytes}, got {size}")
    checksum = file_md5(path)
    if checksum != entry.md5:
        raise ValueError(f"MD5 mismatch for {path.name}: expected {entry.md5}, got {checksum}")
    inspection = inspect_zip(path, entry.kind)
    if not inspection.valid:
        raise ValueError(
            f"field validation failed for {path.name}: {inspection.field_count_histogram}"
        )
    return inspection.to_dict()


def download_entry(
    entry: ManifestEntry,
    directory: Path,
    *,
    timeout: float = 180,
    retries: int = 2,
) -> DownloadResult:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / Path(urlparse(entry.url).path).name
    if destination.exists():
        inspection = _validate_download(entry, destination)
        return DownloadResult(
            entry=entry,
            path=str(destination),
            size_bytes=destination.stat().st_size,
            md5=entry.md5,
            sha256=file_sha256(destination),
            inspection=inspection,
            reused=True,
        )

    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                entry.url,
                headers={"User-Agent": "hello-gdelt/0.1 (+local research validator)"},
            )
            with (
                urllib.request.urlopen(request, timeout=timeout) as response,
                partial.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            inspection = _validate_download(entry, partial)
            partial.replace(destination)
            inspection["path"] = str(destination)
            return DownloadResult(
                entry=entry,
                path=str(destination),
                size_bytes=destination.stat().st_size,
                md5=entry.md5,
                sha256=file_sha256(destination),
                inspection=inspection,
                reused=False,
            )
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 4))
    raise RuntimeError(f"failed to download {entry.url}: {last_error}")
