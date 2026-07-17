from pathlib import Path

import pytest

from hello_gdelt.control.manifest import (
    InvalidStatusTransitionError,
    ManifestConflictError,
    ManifestStore,
)
from hello_gdelt.gdelt.lastupdate import GdeltArtifact


def artifact(
    dataset: str = "events",
    *,
    size: int = 100,
    md5: str = "0" * 32,
) -> GdeltArtifact:
    suffix = {
        "events": "export.CSV.zip",
        "mentions": "mentions.CSV.zip",
        "gkg": "gkg.csv.zip",
    }[dataset]
    return GdeltArtifact(
        size_bytes=size,
        md5=md5,
        url=f"http://data.gdeltproject.org/gdeltv2/20260717054500.{suffix}",
        dataset=dataset,
        timestamp="20260717054500",
    )


def test_register_is_idempotent_and_queryable(tmp_path: Path) -> None:
    with ManifestStore(tmp_path / "control.sqlite3") as store:
        first = store.register([artifact(), artifact("gkg"), artifact("mentions")])
        second = store.register([artifact(), artifact("gkg"), artifact("mentions")])
        assert len(first) == 3
        assert len(second) == 3
        assert len(store.list_by_status("DISCOVERED")) == 3
        assert all(record.attempt_count == 0 for record in second)


def test_manifest_rejects_source_identity_drift(tmp_path: Path) -> None:
    with ManifestStore(tmp_path / "control.sqlite3") as store:
        store.register([artifact()])
        with pytest.raises(ManifestConflictError, match="source identity drift"):
            store.register([artifact(size=101)])


def test_manifest_enforces_transition_contract_and_retry(tmp_path: Path) -> None:
    archive = tmp_path / "archive.zip"
    extracted = tmp_path / "events.tsv"
    bronze = tmp_path / "events.parquet"
    with ManifestStore(tmp_path / "control.sqlite3") as store:
        source_url = store.register([artifact()])[0].source_url
        downloading = store.transition(source_url, "DOWNLOADING")
        assert downloading.attempt_count == 1
        failed = store.transition(source_url, "FAILED", error="temporary network failure")
        assert failed.last_error == "temporary network failure"
        retried = store.transition(source_url, "DOWNLOADING")
        assert retried.attempt_count == 2
        verified = store.transition(
            source_url,
            "VERIFIED",
            local_archive_path=archive,
            actual_sha256="a" * 64,
        )
        assert verified.actual_sha256 == "a" * 64
        extracted_record = store.transition(
            source_url,
            "EXTRACTED",
            local_extracted_path=extracted,
        )
        ready = store.transition(
            source_url,
            "BRONZE_READY",
            bronze_path=bronze,
        )
        assert extracted_record.local_archive_path == str(archive.resolve())
        assert ready.bronze_path == str(bronze.resolve())
        assert ready.last_error is None


def test_manifest_rejects_skipped_state(tmp_path: Path) -> None:
    with ManifestStore(tmp_path / "control.sqlite3") as store:
        source_url = store.register([artifact()])[0].source_url
        with pytest.raises(InvalidStatusTransitionError, match="DISCOVERED -> VERIFIED"):
            store.transition(
                source_url,
                "VERIFIED",
                local_archive_path=tmp_path / "archive.zip",
                actual_sha256="b" * 64,
            )


def test_verified_requires_valid_sha256(tmp_path: Path) -> None:
    with ManifestStore(tmp_path / "control.sqlite3") as store:
        source_url = store.register([artifact()])[0].source_url
        store.transition(source_url, "DOWNLOADING")
        with pytest.raises(ValueError, match="64 hexadecimal"):
            store.transition(
                source_url,
                "VERIFIED",
                local_archive_path=tmp_path / "archive.zip",
                actual_sha256="bad",
            )
