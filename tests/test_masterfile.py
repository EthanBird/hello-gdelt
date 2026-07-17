import pytest

from hello_gdelt.gdelt.masterfile import MasterFileParseError, parse_masterfile


def line(timestamp: str, dataset: str, size: int = 10) -> str:
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


def trio(timestamp: str) -> list[str]:
    return [line(timestamp, "events"), line(timestamp, "mentions"), line(timestamp, "gkg")]


def test_masterfile_materializes_sorted_complete_trios() -> None:
    text = "\n".join(trio("20260717060000") + trio("20260717054500"))
    index = parse_masterfile(text)
    assert [item.timestamp for item in index.trios] == [
        "20260717054500",
        "20260717060000",
    ]
    assert index.incomplete == ()
    assert index.parsed_lines == 6
    assert index.retained_artifacts == 6
    assert index.total_size_bytes == 60


def test_masterfile_reports_incomplete_timestamp() -> None:
    text = "\n".join(
        trio("20260717054500") + [line("20260717060000", "events")]
    )
    index = parse_masterfile(text)
    assert len(index.trios) == 1
    assert index.incomplete[0].timestamp == "20260717060000"
    assert index.incomplete[0].missing_datasets == ("gkg", "mentions")


def test_masterfile_applies_inclusive_timestamp_range() -> None:
    text = "\n".join(
        trio("20260717053000")
        + trio("20260717054500")
        + trio("20260717060000")
    )
    index = parse_masterfile(
        text,
        start_timestamp="20260717054500",
        end_timestamp="20260717054500",
    )
    assert [item.timestamp for item in index.trios] == ["20260717054500"]
    assert index.retained_artifacts == 3


def test_masterfile_rejects_duplicate_dataset_identity() -> None:
    lines = trio("20260717054500")
    lines.append(line("20260717054500", "events", size=11))
    with pytest.raises(MasterFileParseError, match="duplicate events artifact"):
        parse_masterfile("\n".join(lines))


def test_masterfile_enforces_bounded_parse() -> None:
    with pytest.raises(MasterFileParseError, match="exceeded max_lines"):
        parse_masterfile("\n".join(trio("20260717054500")), max_lines=2)


def test_masterfile_rejects_invalid_range() -> None:
    with pytest.raises(ValueError, match="start_timestamp must be <="):
        parse_masterfile(
            "\n".join(trio("20260717054500")),
            start_timestamp="20260717060000",
            end_timestamp="20260717054500",
        )
