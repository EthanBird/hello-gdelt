import pytest

from hello_gdelt.gdelt.lastupdate import LastUpdateParseError, parse_lastupdate


VALID = """\
100 0123456789abcdef0123456789abcdef http://data.gdeltproject.org/gdeltv2/20260716120000.export.CSV.zip
200 1123456789abcdef0123456789abcdef http://data.gdeltproject.org/gdeltv2/20260716120000.mentions.CSV.zip
300 2123456789abcdef0123456789abcdef http://data.gdeltproject.org/gdeltv2/20260716120000.gkg.csv.zip
"""


def test_parse_lastupdate_requires_aligned_trio() -> None:
    artifacts = parse_lastupdate(VALID)
    assert [item.dataset for item in artifacts] == ["events", "gkg", "mentions"]
    assert {item.timestamp for item in artifacts} == {"20260716120000"}


def test_parse_lastupdate_rejects_missing_dataset() -> None:
    with pytest.raises(LastUpdateParseError, match="missing datasets"):
        parse_lastupdate("\n".join(VALID.splitlines()[:2]))


def test_parse_lastupdate_rejects_untrusted_host() -> None:
    with pytest.raises(LastUpdateParseError, match="unexpected host"):
        parse_lastupdate(VALID.replace("data.gdeltproject.org", "example.com", 1))
