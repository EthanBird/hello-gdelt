from hello_gdelt.gdelt.history import plan_backfill
from hello_gdelt.gdelt.masterfile import parse_masterfile


def line(timestamp: str, dataset: str, size: int) -> str:
    suffix = {
        "events": "export.CSV.zip",
        "mentions": "mentions.CSV.zip",
        "gkg": "gkg.csv.zip",
    }[dataset]
    md5 = {"events": "0", "mentions": "1", "gkg": "2"}[dataset] * 32
    return (
        f"{size} {md5} "
        f"http://data.gdeltproject.org/gdeltv2/{timestamp}.{suffix}"
    )


def trio(timestamp: str, size: int = 10) -> list[str]:
    return [
        line(timestamp, "events", size),
        line(timestamp, "mentions", size),
        line(timestamp, "gkg", size),
    ]


def test_plan_backfill_respects_compressed_byte_budget() -> None:
    index = parse_masterfile(
        "\n".join(trio("20260717000000") + trio("20260717001500"))
    )
    plan = plan_backfill(
        index,
        start_timestamp="20260717000000",
        end_timestamp="20260717001500",
        max_compressed_bytes=30,
        max_trios=10,
    )
    assert len(plan.selected_trios) == 1
    assert plan.selected_compressed_bytes == 30
    assert plan.available_compressed_bytes == 60
    assert plan.stopped_by_byte_budget
    assert not plan.stopped_by_trio_limit


def test_plan_backfill_respects_trio_limit() -> None:
    index = parse_masterfile(
        "\n".join(trio("20260717000000") + trio("20260717001500"))
    )
    plan = plan_backfill(
        index,
        start_timestamp="20260717000000",
        end_timestamp="20260717001500",
        max_compressed_bytes=1000,
        max_trios=1,
    )
    assert len(plan.selected_trios) == 1
    assert plan.stopped_by_trio_limit
    assert not plan.stopped_by_byte_budget


def test_plan_preserves_incomplete_timestamps_as_audit_findings() -> None:
    text = "\n".join(
        trio("20260717000000") + [line("20260717001500", "events", 10)]
    )
    index = parse_masterfile(text)
    plan = plan_backfill(
        index,
        start_timestamp="20260717000000",
        end_timestamp="20260717001500",
        max_compressed_bytes=1000,
        max_trios=10,
    )
    assert plan.incomplete_timestamps == ("20260717001500",)
