from collections import namedtuple
from pathlib import Path

import httpx
import pytest

from hello_gdelt.config import ResourceLimits
from hello_gdelt.gdelt.backfill import BackfillExecutionError, execute_backfill_plan
from hello_gdelt.gdelt.gold import GoldReceipt
from hello_gdelt.gdelt.history import BackfillPlan
from hello_gdelt.gdelt.lastupdate import GdeltArtifact
from hello_gdelt.gdelt.masterfile import GdeltArtifactTrio
from hello_gdelt.gdelt.pipeline import ProcessedGdeltTrio


def artifact(timestamp: str, dataset: str) -> GdeltArtifact:
    suffix = {
        "events": "export.CSV.zip",
        "mentions": "mentions.CSV.zip",
        "gkg": "gkg.csv.zip",
    }[dataset]
    return GdeltArtifact(
        size_bytes=10,
        md5="0" * 32,
        url=f"http://data.gdeltproject.org/gdeltv2/{timestamp}.{suffix}",
        dataset=dataset,
        timestamp=timestamp,
    )


def trio(timestamp: str) -> GdeltArtifactTrio:
    return GdeltArtifactTrio(
        timestamp=timestamp,
        artifacts=(
            artifact(timestamp, "events"),
            artifact(timestamp, "gkg"),
            artifact(timestamp, "mentions"),
        ),
    )


def plan(*timestamps: str) -> BackfillPlan:
    selected = tuple(trio(timestamp) for timestamp in timestamps)
    selected_bytes = sum(item.total_size_bytes for item in selected)
    return BackfillPlan(
        start_timestamp=timestamps[0] if timestamps else "20260717000000",
        end_timestamp=timestamps[-1] if timestamps else "20260717000000",
        available_trios=len(selected),
        selected_trios=selected,
        incomplete_timestamps=(),
        selected_compressed_bytes=selected_bytes,
        available_compressed_bytes=selected_bytes,
        stopped_by_byte_budget=False,
        stopped_by_trio_limit=False,
    )


def processed(timestamp: str, tmp_path: Path) -> ProcessedGdeltTrio:
    gold_path = tmp_path / f"{timestamp}.parquet"
    manifest_path = tmp_path / f"{timestamp}.manifest.json"
    return ProcessedGdeltTrio(
        source_timestamp=timestamp,
        datasets=(),
        gold=GoldReceipt(
            source_timestamp=timestamp,
            input_silver_paths=(),
            gold_path=str(gold_path),
            manifest_path=str(manifest_path),
            schema_version="fixture",
            row_count=1,
            gkg_invalid_tone_rows=0,
            gkg_missing_source_rows=0,
            aggregated_at_utc="2026-07-17T00:00:00+00:00",
        ),
    )


def test_empty_backfill_plan_is_rejected(tmp_path: Path) -> None:
    with httpx.Client() as client:
        with pytest.raises(BackfillExecutionError, match="selected no complete trios"):
            execute_backfill_plan(
                client,
                plan(),
                tmp_path,
                limits=ResourceLimits(min_free_disk_bytes=1),
            )


def test_backfill_runs_chronologically_and_stops_on_first_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = ("20260717000000", "20260717001500", "20260717003000")
    calls: list[str] = []

    def fake_process(client, selected_trio, paths, store, **kwargs):
        del client, paths, store, kwargs
        calls.append(selected_trio.timestamp)
        if selected_trio.timestamp == timestamps[1]:
            raise RuntimeError("fixture failure")
        return processed(selected_trio.timestamp, tmp_path)

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "hello_gdelt.gdelt.backfill.shutil.disk_usage",
        lambda path: usage(10_000, 1_000, 9_000),
    )
    monkeypatch.setattr(
        "hello_gdelt.gdelt.backfill.process_gdelt_trio",
        fake_process,
    )
    with httpx.Client() as client:
        result = execute_backfill_plan(
            client,
            plan(*timestamps),
            tmp_path,
            limits=ResourceLimits(min_free_disk_bytes=100),
        )
    assert calls == list(timestamps[:2])
    assert result.completed_count == 1
    assert result.failures[0].source_timestamp == timestamps[1]
    assert result.stopped_early


def test_backfill_can_continue_after_an_isolated_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = ("20260717000000", "20260717001500", "20260717003000")

    def fake_process(client, selected_trio, paths, store, **kwargs):
        del client, paths, store, kwargs
        if selected_trio.timestamp == timestamps[1]:
            raise RuntimeError("fixture failure")
        return processed(selected_trio.timestamp, tmp_path)

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "hello_gdelt.gdelt.backfill.shutil.disk_usage",
        lambda path: usage(10_000, 1_000, 9_000),
    )
    monkeypatch.setattr(
        "hello_gdelt.gdelt.backfill.process_gdelt_trio",
        fake_process,
    )
    with httpx.Client() as client:
        result = execute_backfill_plan(
            client,
            plan(*timestamps),
            tmp_path,
            limits=ResourceLimits(min_free_disk_bytes=100),
            continue_on_error=True,
        )
    assert [item.source_timestamp for item in result.completed_trios] == [
        timestamps[0],
        timestamps[2],
    ]
    assert len(result.failures) == 1
    assert not result.stopped_early
