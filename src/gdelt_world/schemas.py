from __future__ import annotations

import csv
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

EVENT_FIELDS = (
    "GLOBALEVENTID",
    "SQLDATE",
    "MonthYear",
    "Year",
    "FractionDate",
    "Actor1Code",
    "Actor1Name",
    "Actor1CountryCode",
    "Actor1KnownGroupCode",
    "Actor1EthnicCode",
    "Actor1Religion1Code",
    "Actor1Religion2Code",
    "Actor1Type1Code",
    "Actor1Type2Code",
    "Actor1Type3Code",
    "Actor2Code",
    "Actor2Name",
    "Actor2CountryCode",
    "Actor2KnownGroupCode",
    "Actor2EthnicCode",
    "Actor2Religion1Code",
    "Actor2Religion2Code",
    "Actor2Type1Code",
    "Actor2Type2Code",
    "Actor2Type3Code",
    "IsRootEvent",
    "EventCode",
    "EventBaseCode",
    "EventRootCode",
    "QuadClass",
    "GoldsteinScale",
    "NumMentions",
    "NumSources",
    "NumArticles",
    "AvgTone",
    "Actor1Geo_Type",
    "Actor1Geo_FullName",
    "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code",
    "Actor1Geo_ADM2Code",
    "Actor1Geo_Lat",
    "Actor1Geo_Long",
    "Actor1Geo_FeatureID",
    "Actor2Geo_Type",
    "Actor2Geo_FullName",
    "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code",
    "Actor2Geo_ADM2Code",
    "Actor2Geo_Lat",
    "Actor2Geo_Long",
    "Actor2Geo_FeatureID",
    "ActionGeo_Type",
    "ActionGeo_FullName",
    "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code",
    "ActionGeo_ADM2Code",
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "ActionGeo_FeatureID",
    "DATEADDED",
    "SOURCEURL",
)

MENTION_FIELDS = (
    "GLOBALEVENTID",
    "EventTimeDate",
    "MentionTimeDate",
    "MentionType",
    "MentionSourceName",
    "MentionIdentifier",
    "SentenceID",
    "Actor1CharOffset",
    "Actor2CharOffset",
    "ActionCharOffset",
    "InRawText",
    "Confidence",
    "MentionDocLen",
    "MentionDocTone",
    "MentionDocTranslationInfo",
    "Extras",
)

GKG_FIELDS = (
    "GKGRECORDID",
    "DATE",
    "SourceCollectionIdentifier",
    "SourceCommonName",
    "DocumentIdentifier",
    "Counts",
    "V2Counts",
    "Themes",
    "V2Themes",
    "Locations",
    "V2Locations",
    "Persons",
    "V2Persons",
    "Organizations",
    "V2Organizations",
    "V2Tone",
    "Dates",
    "GCAM",
    "SharingImage",
    "RelatedImages",
    "SocialImageEmbeds",
    "SocialVideoEmbeds",
    "Quotations",
    "AllNames",
    "Amounts",
    "TranslationInfo",
    "Extras",
)


@dataclass(frozen=True)
class SchemaSpec:
    kind: str
    fields: tuple[str, ...]

    @property
    def field_count(self) -> int:
        return len(self.fields)


SCHEMAS = {
    "events": SchemaSpec("events", EVENT_FIELDS),
    "mentions": SchemaSpec("mentions", MENTION_FIELDS),
    "gkg": SchemaSpec("gkg", GKG_FIELDS),
}


@dataclass(frozen=True)
class ZipInspection:
    path: str
    kind: str
    member: str
    compressed_bytes: int
    uncompressed_bytes: int
    rows: int
    expected_fields: int
    field_count_histogram: dict[int, int]
    malformed_rows: tuple[int, ...]

    @property
    def valid(self) -> bool:
        return self.rows > 0 and not self.malformed_rows

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["valid"] = self.valid
        return result


def _safe_member(archive: zipfile.ZipFile, *, max_uncompressed_bytes: int) -> zipfile.ZipInfo:
    files = [item for item in archive.infolist() if not item.is_dir()]
    if len(files) != 1:
        raise ValueError(f"expected exactly one file in archive, found {len(files)}")
    member = files[0]
    member_path = Path(member.filename)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"unsafe archive member path: {member.filename}")
    if member.file_size > max_uncompressed_bytes:
        raise ValueError(
            f"archive expands to {member.file_size} bytes; limit is {max_uncompressed_bytes}"
        )
    return member


def iter_tsv_rows(
    path: Path,
    kind: str,
    *,
    max_uncompressed_bytes: int = 1_500_000_000,
) -> Iterator[tuple[int, list[str]]]:
    if kind not in SCHEMAS:
        raise ValueError(f"unknown GDELT dataset kind: {kind}")
    with zipfile.ZipFile(path) as archive:
        member = _safe_member(archive, max_uncompressed_bytes=max_uncompressed_bytes)
        with archive.open(member) as raw:
            lines = (line.decode("utf-8", errors="replace") for line in raw)
            reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
            for row_number, row in enumerate(reader, start=1):
                if not row:
                    continue
                yield row_number, row


def inspect_zip(
    path: Path,
    kind: str,
    *,
    max_errors: int = 20,
    max_uncompressed_bytes: int = 1_500_000_000,
) -> ZipInspection:
    spec = SCHEMAS[kind]
    histogram: Counter[int] = Counter()
    malformed: list[int] = []

    with zipfile.ZipFile(path) as archive:
        member = _safe_member(archive, max_uncompressed_bytes=max_uncompressed_bytes)
        compressed_bytes = member.compress_size
        uncompressed_bytes = member.file_size

    rows = 0
    for row_number, row in iter_tsv_rows(path, kind, max_uncompressed_bytes=max_uncompressed_bytes):
        rows += 1
        histogram[len(row)] += 1
        if len(row) != spec.field_count and len(malformed) < max_errors:
            malformed.append(row_number)

    return ZipInspection(
        path=str(path),
        kind=kind,
        member=member.filename,
        compressed_bytes=compressed_bytes,
        uncompressed_bytes=uncompressed_bytes,
        rows=rows,
        expected_fields=spec.field_count,
        field_count_histogram=dict(sorted(histogram.items())),
        malformed_rows=tuple(malformed),
    )
