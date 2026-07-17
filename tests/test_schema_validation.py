from hello_gdelt.gdelt.schema import validate_tsv_sample


def row(width: int) -> str:
    return "\t".join(str(index) for index in range(width))


def test_events_contract_accepts_61_columns() -> None:
    result = validate_tsv_sample("events", row(61) + "\n" + row(61))
    assert result.passed
    assert result.row_count == 2


def test_mentions_contract_rejects_width_drift() -> None:
    result = validate_tsv_sample("mentions", row(16) + "\n" + row(15))
    assert not result.passed
    assert result.malformed_rows == 1


def test_gkg_contract_accepts_27_columns() -> None:
    assert validate_tsv_sample("gkg", row(27)).passed
