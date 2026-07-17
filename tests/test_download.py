import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from hello_gdelt.config import ResourceLimits
from hello_gdelt.gdelt.download import (
    DownloadError,
    download_artifact,
    extract_single_member_zip,
    fetch_latest_manifest,
)
from hello_gdelt.gdelt.lastupdate import GdeltArtifact


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def test_fetch_manifest_and_download_verified_artifact(tmp_path: Path) -> None:
    body = b"small fixture"
    artifact_url = "https://data.gdeltproject.org/gdeltv2/20260716120000.export.CSV.zip"
    manifest = "\n".join(
        [
            f"{len(body)} {md5(body)} {artifact_url}",
            "1 92eb5ffee6ae2fec3ad71c777531578f https://data.gdeltproject.org/gdeltv2/20260716120000.mentions.CSV.zip",
            "1 0cc175b9c0f1b6a831c399e269772661 https://data.gdeltproject.org/gdeltv2/20260716120000.gkg.csv.zip",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, text=manifest)
        if str(request.url) == artifact_url:
            return httpx.Response(200, content=body, headers={"Content-Length": str(len(body))})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        artifacts = fetch_latest_manifest(client)
        event = next(item for item in artifacts if item.dataset == "events")
        receipt = download_artifact(
            client,
            event,
            tmp_path,
            limits=ResourceLimits(max_download_bytes=1000, min_free_disk_bytes=1),
        )
        reused = download_artifact(client, event, tmp_path)

    assert receipt.path.read_bytes() == body
    assert not receipt.reused
    assert reused.reused


def test_download_hash_mismatch_removes_partial_file(tmp_path: Path) -> None:
    body = b"corrupted"
    artifact = GdeltArtifact(
        size_bytes=len(body),
        md5="0" * 32,
        url="https://data.gdeltproject.org/gdeltv2/20260716120000.export.CSV.zip",
        dataset="events",
        timestamp="20260716120000",
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(DownloadError, match="MD5 mismatch"):
            download_artifact(client, artifact, tmp_path)
    assert not list(tmp_path.glob("*.part"))


def make_zip(filename: str, data: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, data)
    return output.getvalue()


def test_extract_single_member_zip(tmp_path: Path) -> None:
    archive = tmp_path / "fixture.zip"
    archive.write_bytes(make_zip("fixture.tsv", b"a\tb\n"))
    target = extract_single_member_zip(archive, tmp_path / "out")
    assert target.name == "fixture.tsv"
    assert target.read_bytes() == b"a\tb\n"


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    archive.write_bytes(make_zip("../outside.tsv", b"bad"))
    with pytest.raises(DownloadError, match="unsafe ZIP member"):
        extract_single_member_zip(archive, tmp_path / "out")
