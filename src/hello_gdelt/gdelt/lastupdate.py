from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse


class LastUpdateParseError(ValueError):
    """Raised when GDELT lastupdate.txt does not satisfy the expected contract."""


@dataclass(frozen=True, slots=True)
class GdeltArtifact:
    size_bytes: int
    md5: str
    url: str
    dataset: str
    timestamp: str


def _classify(filename: str) -> tuple[str, str]:
    name = PurePosixPath(filename).name
    parts = name.split(".")
    if len(parts) < 4 or not parts[0].isdigit() or len(parts[0]) != 14:
        raise LastUpdateParseError(f"unexpected GDELT filename: {name}")
    timestamp = parts[0]
    if ".export." in name:
        dataset = "events"
    elif ".mentions." in name:
        dataset = "mentions"
    elif ".gkg." in name:
        dataset = "gkg"
    else:
        raise LastUpdateParseError(f"unsupported GDELT artifact: {name}")
    return dataset, timestamp


def parse_lastupdate(text: str) -> tuple[GdeltArtifact, ...]:
    artifacts: list[GdeltArtifact] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise LastUpdateParseError(
                f"line {line_number}: expected '<size> <md5> <url>', got {len(parts)} fields"
            )
        size_raw, md5, url = parts
        try:
            size_bytes = int(size_raw)
        except ValueError as exc:
            raise LastUpdateParseError(f"line {line_number}: invalid byte size") from exc
        if size_bytes <= 0:
            raise LastUpdateParseError(f"line {line_number}: size must be positive")
        if len(md5) != 32 or any(ch not in "0123456789abcdefABCDEF" for ch in md5):
            raise LastUpdateParseError(f"line {line_number}: invalid MD5")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise LastUpdateParseError(f"line {line_number}: URL must be HTTP(S)")
        if parsed.hostname not in {"data.gdeltproject.org", "www.gdeltproject.org"}:
            raise LastUpdateParseError(f"line {line_number}: unexpected host {parsed.hostname}")
        dataset, timestamp = _classify(parsed.path)
        artifacts.append(
            GdeltArtifact(
                size_bytes=size_bytes,
                md5=md5.lower(),
                url=url,
                dataset=dataset,
                timestamp=timestamp,
            )
        )

    if not artifacts:
        raise LastUpdateParseError("lastupdate.txt contained no artifacts")
    datasets = {item.dataset for item in artifacts}
    missing = {"events", "mentions", "gkg"} - datasets
    if missing:
        raise LastUpdateParseError(f"lastupdate.txt missing datasets: {sorted(missing)}")
    timestamps = {item.timestamp for item in artifacts}
    if len(timestamps) != 1:
        raise LastUpdateParseError(f"artifacts are not aligned to one timestamp: {sorted(timestamps)}")
    return tuple(sorted(artifacts, key=lambda item: item.dataset))
