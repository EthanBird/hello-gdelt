from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

from hello_gdelt.config import ResourceLimits
from hello_gdelt.gdelt.lastupdate import GdeltArtifact, parse_lastupdate

LASTUPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"


class DownloadError(RuntimeError):
    """Raised when a remote artifact violates size, hash, or archive contracts."""


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    path: Path
    size_bytes: int
    md5: str
    sha256: str
    reused: bool


def fetch_latest_manifest(
    client: httpx.Client,
    *,
    limits: ResourceLimits | None = None,
    url: str = LASTUPDATE_URL,
) -> tuple[GdeltArtifact, ...]:
    limits = limits or ResourceLimits()
    response = client.get(url, timeout=limits.request_timeout_seconds)
    response.raise_for_status()
    if len(response.content) > 100_000:
        raise DownloadError("lastupdate.txt exceeded the 100KB control-file limit")
    return parse_lastupdate(response.text)


def _hash_file(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> tuple[str, str, int]:
    md5_digest = hashlib.md5(usedforsecurity=False)
    sha256_digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            md5_digest.update(chunk)
            sha256_digest.update(chunk)
            size += len(chunk)
    return md5_digest.hexdigest(), sha256_digest.hexdigest(), size


def download_artifact(
    client: httpx.Client,
    artifact: GdeltArtifact,
    destination_dir: Path,
    *,
    limits: ResourceLimits | None = None,
) -> DownloadReceipt:
    limits = limits or ResourceLimits()
    if artifact.size_bytes > limits.max_download_bytes:
        raise DownloadError(
            f"manifest size {artifact.size_bytes:,} exceeds max_download_bytes="
            f"{limits.max_download_bytes:,}"
        )

    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = PurePosixPath(httpx.URL(artifact.url).path).name
    if not filename or filename in {".", ".."}:
        raise DownloadError("artifact URL contains no safe filename")
    final_path = destination_dir / filename
    part_path = destination_dir / f".{filename}.part"

    if final_path.exists():
        md5, sha256, size = _hash_file(final_path)
        if size == artifact.size_bytes and md5 == artifact.md5:
            return DownloadReceipt(final_path, size, md5, sha256, True)
        raise DownloadError(f"existing artifact failed manifest verification: {final_path}")

    part_path.unlink(missing_ok=True)
    md5_digest = hashlib.md5(usedforsecurity=False)
    sha256_digest = hashlib.sha256()
    downloaded = 0
    try:
        with client.stream(
            "GET",
            artifact.url,
            timeout=limits.request_timeout_seconds,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_remote = int(content_length)
                except ValueError as exc:
                    raise DownloadError("remote Content-Length is not an integer") from exc
                if declared_remote != artifact.size_bytes:
                    raise DownloadError(
                        "remote Content-Length does not match GDELT manifest: "
                        f"remote={declared_remote}, manifest={artifact.size_bytes}"
                    )
            with part_path.open("xb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > artifact.size_bytes:
                        raise DownloadError("download exceeded manifest byte size")
                    if downloaded > limits.max_download_bytes:
                        raise DownloadError("download exceeded configured byte limit")
                    md5_digest.update(chunk)
                    sha256_digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_md5 = md5_digest.hexdigest()
        actual_sha256 = sha256_digest.hexdigest()
        if downloaded != artifact.size_bytes:
            raise DownloadError(
                f"download byte mismatch: actual={downloaded}, manifest={artifact.size_bytes}"
            )
        if actual_md5 != artifact.md5:
            raise DownloadError(
                f"download MD5 mismatch: actual={actual_md5}, manifest={artifact.md5}"
            )
        os.replace(part_path, final_path)
        return DownloadReceipt(
            final_path,
            downloaded,
            actual_md5,
            actual_sha256,
            False,
        )
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def extract_single_member_zip(
    archive_path: Path,
    destination_dir: Path,
    *,
    max_uncompressed_bytes: int = 5_000_000_000,
    max_compression_ratio: float = 250.0,
) -> Path:
    if max_uncompressed_bytes <= 0:
        raise ValueError("max_uncompressed_bytes must be positive")
    if max_compression_ratio <= 0:
        raise ValueError("max_compression_ratio must be positive")
    destination_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) != 1:
            raise DownloadError(f"expected one data member, found {len(members)}")
        member = members[0]
        member_path = PurePosixPath(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts or len(member_path.parts) != 1:
            raise DownloadError(f"unsafe ZIP member path: {member.filename}")
        if member.file_size <= 0 or member.file_size > max_uncompressed_bytes:
            raise DownloadError(
                f"uncompressed member size outside bounds: {member.file_size:,} bytes"
            )
        compressed = max(member.compress_size, 1)
        ratio = member.file_size / compressed
        if ratio > max_compression_ratio:
            raise DownloadError(f"ZIP compression ratio {ratio:.1f} exceeds safety limit")

        target = destination_dir / member_path.name
        part = destination_dir / f".{member_path.name}.part"
        part.unlink(missing_ok=True)
        try:
            with archive.open(member) as source, part.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if part.stat().st_size != member.file_size:
                raise DownloadError("extracted byte size differs from ZIP central directory")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise DownloadError(f"ZIP CRC validation failed for {bad_member}")
            os.replace(part, target)
            return target
        except Exception:
            part.unlink(missing_ok=True)
            raise
