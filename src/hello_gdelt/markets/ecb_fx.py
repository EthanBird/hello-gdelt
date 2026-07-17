from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

ECB_DATA_API = "https://data-api.ecb.europa.eu/service/data/EXR"

FX_PAIR_COMPONENTS: dict[str, tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"),
    "USDJPY": ("USD", "JPY"),
    "GBPUSD": ("GBP", "USD"),
    "USDCHF": ("USD", "CHF"),
    "USDCNY": ("USD", "CNY"),
    "USDKRW": ("USD", "KRW"),
    "AUDUSD": ("AUD", "USD"),
    "NZDUSD": ("NZD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "USDSEK": ("USD", "SEK"),
    "USDNOK": ("USD", "NOK"),
    "USDINR": ("USD", "INR"),
    "USDSGD": ("USD", "SGD"),
    "USDHKD": ("USD", "HKD"),
    "EURJPY": ("EUR", "JPY"),
    "EURGBP": ("EUR", "GBP"),
}


class EcbFxContractError(ValueError):
    """Raised when ECB EXR data violates the frozen daily-reference contract."""


@dataclass(frozen=True, slots=True)
class EcbFxObservation:
    observation_date: date
    currency: str
    currency_per_eur: float
    observation_status: str | None
    series_key: str | None


@dataclass(frozen=True, slots=True)
class FxPairObservation:
    observation_date: date
    pair: str
    base_currency: str
    quote_currency: str
    quote_per_base: float
    source: str = "ECB_EXR_DAILY_REFERENCE"


@dataclass(frozen=True, slots=True)
class EcbFxReceipt:
    request_url: str
    response_sha256: str
    start_date: str
    end_date: str
    currencies: tuple[str, ...]
    pair_names: tuple[str, ...]
    raw_observation_count: int
    pair_observation_count: int
    first_observation_date: str
    last_observation_date: str
    parquet_path: str
    manifest_path: str
    schema_version: str


def required_ecb_currencies(
    pair_components: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, ...]:
    pairs = pair_components or FX_PAIR_COMPONENTS
    currencies = {
        currency
        for base_quote in pairs.values()
        for currency in base_quote
        if currency != "EUR"
    }
    return tuple(sorted(currencies))


def _validate_currency_code(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise EcbFxContractError(f"invalid ISO-style currency code: {currency!r}")
    return normalized


def build_ecb_exr_url(
    currencies: tuple[str, ...],
    *,
    start_date: date,
    end_date: date,
) -> str:
    if start_date > end_date:
        raise EcbFxContractError("start_date must be <= end_date")
    normalized = tuple(sorted({_validate_currency_code(item) for item in currencies}))
    if not normalized:
        raise EcbFxContractError("at least one non-EUR currency is required")
    if "EUR" in normalized:
        raise EcbFxContractError("EUR is the denominator and must not be queried as a currency")
    if len(normalized) > 60:
        raise EcbFxContractError("currency query exceeds the 60-series safety limit")
    series_key = f"D.{'+'.join(normalized)}.EUR.SP00.A"
    query = urlencode(
        {
            "startPeriod": start_date.isoformat(),
            "endPeriod": end_date.isoformat(),
            "format": "csvdata",
            "detail": "dataonly",
        }
    )
    return f"{ECB_DATA_API}/{series_key}?{query}"


def _find_column(fieldnames: tuple[str, ...], *candidates: str) -> str | None:
    lookup = {name.strip().upper(): name for name in fieldnames}
    for candidate in candidates:
        found = lookup.get(candidate.upper())
        if found is not None:
            return found
    return None


def parse_ecb_exr_csv(
    text: str,
    *,
    expected_currencies: tuple[str, ...] | None = None,
) -> tuple[EcbFxObservation, ...]:
    cleaned = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(cleaned))
    if reader.fieldnames is None:
        raise EcbFxContractError("ECB CSV has no header")
    fieldnames = tuple(reader.fieldnames)
    currency_col = _find_column(fieldnames, "CURRENCY")
    denominator_col = _find_column(fieldnames, "CURRENCY_DENOM")
    frequency_col = _find_column(fieldnames, "FREQ")
    type_col = _find_column(fieldnames, "EXR_TYPE")
    suffix_col = _find_column(fieldnames, "EXR_SUFFIX")
    date_col = _find_column(fieldnames, "TIME_PERIOD")
    value_col = _find_column(fieldnames, "OBS_VALUE")
    status_col = _find_column(fieldnames, "OBS_STATUS")
    key_col = _find_column(fieldnames, "KEY", "SERIES_KEY")
    required = {
        "CURRENCY": currency_col,
        "CURRENCY_DENOM": denominator_col,
        "FREQ": frequency_col,
        "EXR_TYPE": type_col,
        "EXR_SUFFIX": suffix_col,
        "TIME_PERIOD": date_col,
        "OBS_VALUE": value_col,
    }
    missing = [logical for logical, physical in required.items() if physical is None]
    if missing:
        raise EcbFxContractError(
            f"ECB CSV missing required columns {missing}; actual={list(fieldnames)}"
        )

    expected = (
        {_validate_currency_code(item) for item in expected_currencies}
        if expected_currencies is not None
        else None
    )
    observations: list[EcbFxObservation] = []
    seen: set[tuple[date, str]] = set()
    for row_number, row in enumerate(reader, start=2):
        currency = _validate_currency_code(row[currency_col].strip())  # type: ignore[index]
        denominator = row[denominator_col].strip().upper()  # type: ignore[index]
        frequency = row[frequency_col].strip().upper()  # type: ignore[index]
        exr_type = row[type_col].strip().upper()  # type: ignore[index]
        suffix = row[suffix_col].strip().upper()  # type: ignore[index]
        if denominator != "EUR" or frequency != "D" or exr_type != "SP00" or suffix != "A":
            raise EcbFxContractError(
                f"row {row_number}: unexpected series identity "
                f"{frequency}.{currency}.{denominator}.{exr_type}.{suffix}"
            )
        try:
            observation_date = date.fromisoformat(row[date_col].strip())  # type: ignore[index]
        except ValueError as exc:
            raise EcbFxContractError(f"row {row_number}: invalid TIME_PERIOD") from exc
        try:
            value = float(row[value_col])  # type: ignore[index]
        except (TypeError, ValueError) as exc:
            raise EcbFxContractError(f"row {row_number}: invalid OBS_VALUE") from exc
        if not math.isfinite(value) or value <= 0:
            raise EcbFxContractError(
                f"row {row_number}: OBS_VALUE must be positive and finite"
            )
        identity = (observation_date, currency)
        if identity in seen:
            raise EcbFxContractError(f"duplicate ECB observation: {identity}")
        seen.add(identity)
        observations.append(
            EcbFxObservation(
                observation_date=observation_date,
                currency=currency,
                currency_per_eur=value,
                observation_status=(
                    row[status_col].strip() or None if status_col is not None else None
                ),
                series_key=(row[key_col].strip() or None if key_col is not None else None),
            )
        )

    if not observations:
        raise EcbFxContractError("ECB CSV contains no observations")
    actual_currencies = {item.currency for item in observations}
    if expected is not None:
        unexpected = actual_currencies - expected
        if unexpected:
            raise EcbFxContractError(
                f"ECB response included unexpected currencies: {sorted(unexpected)}"
            )
        missing_all = expected - actual_currencies
        if missing_all:
            raise EcbFxContractError(
                f"ECB response contains no observations for currencies: {sorted(missing_all)}"
            )
    return tuple(sorted(observations, key=lambda item: (item.observation_date, item.currency)))


def derive_fx_pairs(
    observations: tuple[EcbFxObservation, ...],
    *,
    pair_components: dict[str, tuple[str, str]] | None = None,
    require_complete_dates: bool = True,
) -> tuple[FxPairObservation, ...]:
    pairs = pair_components or FX_PAIR_COMPONENTS
    by_date: dict[date, dict[str, float]] = defaultdict(dict)
    for observation in observations:
        by_date[observation.observation_date][observation.currency] = (
            observation.currency_per_eur
        )
    derived: list[FxPairObservation] = []
    for observation_date in sorted(by_date):
        rates = {"EUR": 1.0, **by_date[observation_date]}
        missing: set[str] = set()
        for base_currency, quote_currency in pairs.values():
            if base_currency not in rates:
                missing.add(base_currency)
            if quote_currency not in rates:
                missing.add(quote_currency)
        if missing:
            if require_complete_dates:
                raise EcbFxContractError(
                    f"{observation_date}: missing currencies for frozen FX panel: {sorted(missing)}"
                )
            continue
        for pair, (base_currency, quote_currency) in sorted(pairs.items()):
            value = rates[quote_currency] / rates[base_currency]
            if not math.isfinite(value) or value <= 0:
                raise EcbFxContractError(
                    f"{observation_date} {pair}: derived rate is not positive and finite"
                )
            derived.append(
                FxPairObservation(
                    observation_date=observation_date,
                    pair=pair,
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    quote_per_base=value,
                )
            )
    if not derived:
        raise EcbFxContractError("no complete FX pair observations could be derived")
    return tuple(derived)


def fetch_ecb_exr_csv(
    client: httpx.Client,
    *,
    currencies: tuple[str, ...],
    start_date: date,
    end_date: date,
    timeout_seconds: float = 90.0,
    max_response_bytes: int = 50_000_000,
) -> tuple[str, str, str]:
    url = build_ecb_exr_url(currencies, start_date=start_date, end_date=end_date)
    response = client.get(
        url,
        headers={"Accept": "text/csv,application/vnd.sdmx.data+csv;version=2.0.0"},
        timeout=timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    if len(response.content) > max_response_bytes:
        raise EcbFxContractError(
            f"ECB response exceeded max_response_bytes={max_response_bytes:,}"
        )
    content_type = response.headers.get("content-type", "").lower()
    if "csv" not in content_type and not response.text.lstrip("\ufeff").startswith(
        ("KEY,", "FREQ,")
    ):
        raise EcbFxContractError(
            f"ECB response is not recognizable CSV: content-type={content_type!r}"
        )
    sha256 = hashlib.sha256(response.content).hexdigest()
    return response.text, str(response.url), sha256


def _load_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise RuntimeError(
            "Polars is required to persist ECB FX data; install with pip install -e '.[data]'"
        ) from exc
    return pl


def write_ecb_fx_parquet(
    pairs: tuple[FxPairObservation, ...],
    root: Path,
    *,
    request_url: str,
    response_sha256: str,
    currencies: tuple[str, ...],
    raw_observation_count: int,
    schema_version: str = "ecb-exr-fx-pairs-v1",
    overwrite: bool = False,
) -> EcbFxReceipt:
    if not pairs:
        raise EcbFxContractError("cannot persist an empty FX pair panel")
    dates = sorted({item.observation_date for item in pairs})
    pair_names = tuple(sorted({item.pair for item in pairs}))
    start_date = dates[0]
    end_date = dates[-1]
    target = (
        root
        / "silver"
        / "markets"
        / "ecb_fx"
        / f"year={start_date.year:04d}"
        / f"part-{start_date.isoformat()}-{end_date.isoformat()}.parquet"
    )
    manifest = target.with_suffix(".manifest.json")
    if target.exists() and not overwrite:
        if manifest.exists():
            stored = EcbFxReceipt(**json.loads(manifest.read_text(encoding="utf-8")))
            if stored.response_sha256 == response_sha256 and Path(stored.parquet_path).is_file():
                return stored
        raise FileExistsError(target)
    pl = _load_polars()
    frame = pl.DataFrame(
        {
            "observation_date": [item.observation_date for item in pairs],
            "pair": [item.pair for item in pairs],
            "base_currency": [item.base_currency for item in pairs],
            "quote_currency": [item.quote_currency for item in pairs],
            "quote_per_base": [item.quote_per_base for item in pairs],
            "source": [item.source for item in pairs],
            "_request_url": [request_url] * len(pairs),
            "_response_sha256": [response_sha256] * len(pairs),
            "_schema_version": [schema_version] * len(pairs),
        }
    )
    if frame.select(["observation_date", "pair"]).is_duplicated().any():
        raise EcbFxContractError("derived FX panel contains duplicate date/pair rows")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    manifest_part = manifest.with_name(f".{manifest.name}.part")
    part.unlink(missing_ok=True)
    manifest_part.unlink(missing_ok=True)
    try:
        frame.write_parquet(part, compression="zstd", compression_level=6, statistics=True)
        receipt = EcbFxReceipt(
            request_url=request_url,
            response_sha256=response_sha256,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            currencies=tuple(sorted(currencies)),
            pair_names=pair_names,
            raw_observation_count=raw_observation_count,
            pair_observation_count=len(pairs),
            first_observation_date=start_date.isoformat(),
            last_observation_date=end_date.isoformat(),
            parquet_path=str(target.resolve()),
            manifest_path=str(manifest.resolve()),
            schema_version=schema_version,
        )
        manifest_part.write_text(
            json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(part, target)
        os.replace(manifest_part, manifest)
        return receipt
    except Exception:
        part.unlink(missing_ok=True)
        manifest_part.unlink(missing_ok=True)
        raise
