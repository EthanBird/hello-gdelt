from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from hello_gdelt.gdelt.masterfile import GdeltArtifactTrio, MasterFileIndex, parse_masterfile_lines

MASTERFILE_HTTPS_URL = "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
MASTERFILE_HTTP_URL = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"

TransportSecurity = Literal["HTTPS", "HTTP_FALLBACK"]


class HistoricalManifestError(RuntimeError):
    """Raised when the GDELT historical file catalogue exceeds a safety contract."""


@dataclass(frozen=True, slots=True)
class HistoricalManifestReceipt:
    path: str
    source_url: str
    transport_security: TransportSecurity
    size_bytes: int
    sha256: str
    reused: bool


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    start_timestamp: str
    end_timestamp: str
    available_trios: int
    selected_trios: tuple[GdeltArtifactTrio, ...]
    incomplete_timestamps: tuple[str, ...]
    selected_compressed_bytes: int
    available_compressed_bytes: int
    stopped_by_byte_budget: bool
    stopped_by_trio_limit: bool


def fetch_historical_manifest(
    client: httpx.Client,
    destination: Path,
    *,
    allow_insecure_http: bool = False,
    timeout_seconds: float = 180.0,
    max_response_bytes: int = 500_000_000,
    refresh: bool = True,
) -> HistoricalManifestReceipt:
    """Fetch the append-only GDELT 2 master list with an explicit transport audit."""

    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not refresh:
        digest = hashlib.sha256()
        size = 0
        with destination.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return HistoricalManifestReceipt(
            path=str(destination),
            source_url="LOCAL_REUSE",
            transport_security="HTTP_FALLBACK",
            size_bytes=size,
            sha256=digest.hexdigest(),
            reused=True,
        )

    source_url = MASTERFILE_HTTPS_URL
    transport_security: TransportSecurity = "HTTPS"
    try:
        response_context = client.stream(
            "GET",
            source_url,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response = response_context.__enter__()
        response.raise_for_status()
    except httpx.TransportError:
        try:
            response_context.__exit__(None, None, None)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        if not allow_insecure_http:
            raise
        source_url = MASTERFILE_HTTP_URL
        transport_security = "HTTP_FALLBACK"
        response_context = client.stream(
            "GET",
            source_url,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response = response_context.__enter__()
        response.raise_for_status()

    part = destination.with_name(f".{destination.name}.part")
    part.unlink(missing_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError as exc:
                raise HistoricalManifestError("master file Content-Length is invalid") from exc
            if declared > max_response_bytes:
                raise HistoricalManifestError(
                    f"master file Content-Length {declared:,} exceeds limit "
                    f"{max_response_bytes:,}"
                )
        with part.open("xb") as handle:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_response_bytes:
                    raise HistoricalManifestError(
                        f"master file exceeded max_response_bytes={max_response_bytes:,}"
                    )
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise HistoricalManifestError("master file response was empty")
        os.replace(part, destination)
        return HistoricalManifestReceipt(
            path=str(destination),
            source_url=source_url,
            transport_security=transport_security,
            size_bytes=size,
            sha256=digest.hexdigest(),
            reused=False,
        )
    except Exception:
        part.unlink(missing_ok=True)
        raise
    finally:
        response_context.__exit__(None, None, None)


def index_historical_range(
    manifest_path: Path,
    *,
    start_timestamp: str,
    end_timestamp: str,
    max_lines: int = 2_000_000,
) -> MasterFileIndex:
    with manifest_path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
        return parse_masterfile_lines(
            handle,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            max_lines=max_lines,
        )


def plan_backfill(
    index: MasterFileIndex,
    *,
    start_timestamp: str,
    end_timestamp: str,
    max_compressed_bytes: int,
    max_trios: int,
) -> BackfillPlan:
    if max_compressed_bytes <= 0:
        raise ValueError("max_compressed_bytes must be positive")
    if max_trios <= 0:
        raise ValueError("max_trios must be positive")
    selected: list[GdeltArtifactTrio] = []
    selected_bytes = 0
    stopped_by_byte_budget = False
    stopped_by_trio_limit = False
    for trio in index.trios:
        if len(selected) >= max_trios:
            stopped_by_trio_limit = True
            break
        proposed = selected_bytes + trio.total_size_bytes
        if proposed > max_compressed_bytes:
            stopped_by_byte_budget = True
            break
        selected.append(trio)
        selected_bytes = proposed
    return BackfillPlan(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        available_trios=len(index.trios),
        selected_trios=tuple(selected),
        incomplete_timestamps=tuple(item.timestamp for item in index.incomplete),
        selected_compressed_bytes=selected_bytes,
        available_compressed_bytes=index.total_size_bytes,
        stopped_by_byte_budget=stopped_by_byte_budget,
        stopped_by_trio_limit=stopped_by_trio_limit,
    )
