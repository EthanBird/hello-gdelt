from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

BASE_URL = "https://data.gdeltproject.org/events"
USER_AGENT = "hello-gdelt-raw-event-pilot/1.0 (+https://github.com/EthanBird/hello-gdelt)"
EVENT_COLUMNS = [
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
    "Actor1Geo_Lat",
    "Actor1Geo_Long",
    "Actor1Geo_FeatureID",
    "Actor2Geo_Type",
    "Actor2Geo_FullName",
    "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code",
    "Actor2Geo_Lat",
    "Actor2Geo_Long",
    "Actor2Geo_FeatureID",
    "ActionGeo_Type",
    "ActionGeo_FullName",
    "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code",
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "ActionGeo_FeatureID",
    "DATEADDED",
    "SOURCEURL",
]
KEEP_COLUMNS = [
    "GLOBALEVENTID",
    "SQLDATE",
    "Actor1Code",
    "Actor1Name",
    "Actor1CountryCode",
    "Actor2Code",
    "Actor2Name",
    "Actor2CountryCode",
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
    "ActionGeo_CountryCode",
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "DATEADDED",
    "SOURCEURL",
]
NUMERIC_COLUMNS = [
    "GLOBALEVENTID",
    "SQLDATE",
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
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "DATEADDED",
]


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_bytes(url: str, *, retries: int = 6) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            wait = 30 if exc.code == 429 else min(60, 3 * (attempt + 1))
            time.sleep(wait)
        except Exception as exc:
            last_error = exc
            time.sleep(min(60, 3 * (attempt + 1)))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def parse_md5sums(payload: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in payload.splitlines():
        match = re.match(r"^([0-9a-fA-F]{32})\s+\*?(.+)$", line.strip())
        if match:
            mapping[Path(match.group(2)).name] = match.group(1).lower()
    return mapping


def dates_between(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end precedes start")
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def source_domain(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        host = urlparse(value).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.lower().removeprefix("www.")


def weighted_average(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(values[mask].astype(float), weights=weights[mask].astype(float)))


def read_zip(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"corrupt member: {bad_member}")
        members = [member for member in archive.namelist() if not member.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"expected one member, found {members}")
        member = members[0]
        with archive.open(member) as handle:
            raw = pd.read_csv(
                handle,
                sep="\t",
                header=None,
                names=EVENT_COLUMNS,
                dtype=str,
                on_bad_lines="skip",
                low_memory=False,
            )
    for column in NUMERIC_COLUMNS:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["source_domain"] = raw["SOURCEURL"].map(source_domain)
    raw["event_date"] = pd.to_datetime(
        raw["SQLDATE"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    audit = {
        "zip_member": member,
        "rows": int(len(raw)),
        "duplicate_event_ids": int(raw["GLOBALEVENTID"].duplicated().sum()),
        "missing_fraction": {
            column: float(raw[column].isna().mean())
            for column in [
                "GLOBALEVENTID",
                "SQLDATE",
                "EventRootCode",
                "QuadClass",
                "GoldsteinScale",
                "NumMentions",
                "AvgTone",
                "SOURCEURL",
            ]
        },
    }
    return raw, audit


def global_daily(events: pd.DataFrame, day: date) -> dict[str, Any]:
    mentions = events["NumMentions"].fillna(0).clip(lower=0)
    quad = events["QuadClass"]
    return {
        "date": day.isoformat(),
        "event_count": int(len(events)),
        "root_event_count": int((events["IsRootEvent"] == 1).sum()),
        "mention_total": float(events["NumMentions"].sum(skipna=True)),
        "source_total": float(events["NumSources"].sum(skipna=True)),
        "article_total": float(events["NumArticles"].sum(skipna=True)),
        "unique_source_domains": int(events["source_domain"].nunique(dropna=True)),
        "verbal_cooperation_share": float((quad == 1).mean()),
        "material_cooperation_share": float((quad == 2).mean()),
        "verbal_conflict_share": float((quad == 3).mean()),
        "material_conflict_share": float((quad == 4).mean()),
        "tone_weighted_mentions": weighted_average(events["AvgTone"], mentions),
        "goldstein_weighted_mentions": weighted_average(
            events["GoldsteinScale"], mentions
        ),
    }


def country_daily(events: pd.DataFrame, day: date) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    roles = {
        "actor1": "Actor1CountryCode",
        "actor2": "Actor2CountryCode",
        "action_geo": "ActionGeo_CountryCode",
    }
    for role, column in roles.items():
        subset = events.dropna(subset=[column]).copy()
        if subset.empty:
            continue
        subset["country_code"] = subset[column].astype(str)
        subset["conflict"] = subset["QuadClass"].isin([3, 4]).astype(int)
        subset["material_conflict"] = (subset["QuadClass"] == 4).astype(int)
        grouped = subset.groupby("country_code", as_index=False).agg(
            event_count=("GLOBALEVENTID", "size"),
            mention_total=("NumMentions", "sum"),
            source_total=("NumSources", "sum"),
            article_total=("NumArticles", "sum"),
            conflict_share=("conflict", "mean"),
            material_conflict_share=("material_conflict", "mean"),
            avg_tone=("AvgTone", "mean"),
            avg_goldstein=("GoldsteinScale", "mean"),
            unique_source_domains=("source_domain", "nunique"),
        )
        grouped.insert(0, "date", day.isoformat())
        grouped.insert(1, "role", role)
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bilateral_daily(events: pd.DataFrame, day: date) -> pd.DataFrame:
    subset = events.dropna(
        subset=["Actor1CountryCode", "Actor2CountryCode", "EventRootCode"]
    ).copy()
    if subset.empty:
        return pd.DataFrame()
    subset["Actor1CountryCode"] = subset["Actor1CountryCode"].astype(str)
    subset["Actor2CountryCode"] = subset["Actor2CountryCode"].astype(str)
    subset["EventRootCode"] = subset["EventRootCode"].astype("Int64")
    subset["conflict"] = subset["QuadClass"].isin([3, 4]).astype(int)
    grouped = subset.groupby(
        ["Actor1CountryCode", "Actor2CountryCode", "EventRootCode"], as_index=False
    ).agg(
        event_count=("GLOBALEVENTID", "size"),
        mention_total=("NumMentions", "sum"),
        source_total=("NumSources", "sum"),
        conflict_share=("conflict", "mean"),
        avg_tone=("AvgTone", "mean"),
        avg_goldstein=("GoldsteinScale", "mean"),
    )
    grouped.insert(0, "date", day.isoformat())
    return grouped


def run(start: date, end: date, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    silver_dir = output / "silver"
    raw_dir.mkdir(exist_ok=True)
    silver_dir.mkdir(exist_ok=True)
    md5_payload = fetch_bytes(f"{BASE_URL}/md5sums").decode("utf-8", errors="replace")
    (output / "md5sums.txt").write_text(md5_payload, encoding="utf-8")
    expected_md5 = parse_md5sums(md5_payload)
    manifests: list[dict[str, Any]] = []
    global_rows: list[dict[str, Any]] = []
    country_frames: list[pd.DataFrame] = []
    bilateral_frames: list[pd.DataFrame] = []
    for day in dates_between(start, end):
        stamp = day.strftime("%Y%m%d")
        filename = f"{stamp}.export.CSV.zip"
        url = f"{BASE_URL}/{filename}"
        path = raw_dir / filename
        payload = fetch_bytes(url)
        path.write_bytes(payload)
        local_md5 = digest(path, "md5")
        expected = expected_md5.get(filename)
        if expected is None:
            raise ValueError(f"{filename}: missing official MD5")
        if local_md5 != expected:
            raise ValueError(
                f"{filename}: MD5 mismatch expected={expected} actual={local_md5}"
            )
        events, audit = read_zip(path)
        expected_sql_date = int(stamp)
        date_match = float((events["SQLDATE"] == expected_sql_date).mean())
        if date_match < 0.99:
            raise ValueError(f"{filename}: SQLDATE match {date_match:.6f} < 0.99")
        selected = events[KEEP_COLUMNS + ["source_domain", "event_date"]].copy()
        silver_path = silver_dir / f"date={day.isoformat()}.parquet"
        selected.to_parquet(silver_path, index=False, compression="zstd")
        global_rows.append(global_daily(events, day))
        country_frames.append(country_daily(events, day))
        bilateral_frames.append(bilateral_daily(events, day))
        manifests.append(
            {
                "date": day.isoformat(),
                "url": url,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "zip_bytes": path.stat().st_size,
                "expected_md5": expected,
                "local_md5": local_md5,
                "sha256": digest(path, "sha256"),
                "sql_date_match": date_match,
                "silver_path": str(silver_path.relative_to(output)),
                "silver_sha256": digest(silver_path, "sha256"),
                **audit,
            }
        )
        print(f"{day}: {len(events):,} events, {path.stat().st_size / 1e6:.1f} MB")
        time.sleep(1)
    pd.DataFrame(global_rows).to_parquet(
        output / "global_day_state.parquet", index=False, compression="zstd"
    )
    pd.concat(country_frames, ignore_index=True).to_parquet(
        output / "country_day_state.parquet", index=False, compression="zstd"
    )
    pd.concat(bilateral_frames, ignore_index=True).to_parquet(
        output / "bilateral_day_relation.parquet", index=False, compression="zstd"
    )
    report = {
        "study_id": "gdelt-daily-event-raw-pilot",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": len(manifests),
        "total_events": sum(item["rows"] for item in manifests),
        "total_zip_bytes": sum(item["zip_bytes"] for item in manifests),
        "all_md5_verified": all(
            item["expected_md5"] == item["local_md5"] for item in manifests
        ),
        "daily_manifest": manifests,
    }
    (output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in report if key != "daily_manifest"}, indent=2))


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=parse_date, default=date(2025, 7, 18))
    parser.add_argument("--end", type=parse_date, default=date(2025, 7, 31))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("RAW_EVENT_OUTPUT", "raw_event_output")),
    )
    args = parser.parse_args()
    run(args.start, args.end, args.output)


if __name__ == "__main__":
    main()
