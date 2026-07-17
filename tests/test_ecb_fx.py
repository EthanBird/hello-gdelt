from datetime import date
from pathlib import Path

import pytest

from hello_gdelt.markets.ecb_fx import (
    FX_PAIR_COMPONENTS,
    EcbFxContractError,
    build_ecb_exr_url,
    derive_fx_pairs,
    parse_ecb_exr_csv,
    required_ecb_currencies,
    write_ecb_fx_parquet,
)

HEADER = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,"
    "TIME_PERIOD,OBS_VALUE,OBS_STATUS"
)


def row(currency: str, value: float, day: str = "2026-07-16") -> str:
    return (
        f"EXR.D.{currency}.EUR.SP00.A,D,{currency},EUR,SP00,A,"
        f"{day},{value},A"
    )


def complete_csv(day: str = "2026-07-16") -> str:
    values = {
        "USD": 1.2,
        "JPY": 180.0,
        "GBP": 0.8,
        "CHF": 0.96,
        "CNY": 8.4,
        "KRW": 1680.0,
        "AUD": 1.8,
        "NZD": 1.92,
        "CAD": 1.56,
        "SEK": 12.0,
        "NOK": 12.6,
        "INR": 102.0,
        "SGD": 1.62,
        "HKD": 9.36,
    }
    return "\n".join([HEADER, *(row(currency, value, day) for currency, value in values.items())])


def test_build_ecb_url_uses_daily_reference_series() -> None:
    url = build_ecb_exr_url(
        ("JPY", "USD"),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 16),
    )
    assert "/EXR/D.JPY+USD.EUR.SP00.A?" in url
    assert "startPeriod=2026-07-01" in url
    assert "endPeriod=2026-07-16" in url
    assert "format=csvdata" in url


def test_parse_and_derive_all_frozen_fx_pairs() -> None:
    currencies = required_ecb_currencies()
    observations = parse_ecb_exr_csv(complete_csv(), expected_currencies=currencies)
    pairs = derive_fx_pairs(observations)
    values = {item.pair: item.quote_per_base for item in pairs}
    assert len(observations) == len(currencies)
    assert set(values) == set(FX_PAIR_COMPONENTS)
    assert values["EURUSD"] == pytest.approx(1.2)
    assert values["USDJPY"] == pytest.approx(150.0)
    assert values["GBPUSD"] == pytest.approx(1.5)
    assert values["USDCNY"] == pytest.approx(7.0)
    assert values["EURGBP"] == pytest.approx(0.8)


def test_parser_rejects_series_identity_drift() -> None:
    bad = complete_csv().replace(",EUR,SP00,A,", ",USD,SP00,A,", 1)
    with pytest.raises(EcbFxContractError, match="unexpected series identity"):
        parse_ecb_exr_csv(bad)


def test_parser_rejects_duplicate_date_currency() -> None:
    duplicate = complete_csv() + "\n" + row("USD", 1.2)
    with pytest.raises(EcbFxContractError, match="duplicate ECB observation"):
        parse_ecb_exr_csv(duplicate)


def test_derivation_rejects_incomplete_frozen_panel() -> None:
    observations = parse_ecb_exr_csv("\n".join([HEADER, row("USD", 1.2)]))
    with pytest.raises(EcbFxContractError, match="missing currencies"):
        derive_fx_pairs(observations)


def test_write_ecb_pair_panel_is_idempotent(tmp_path: Path) -> None:
    pytest.importorskip("polars")
    observations = parse_ecb_exr_csv(
        complete_csv(),
        expected_currencies=required_ecb_currencies(),
    )
    pairs = derive_fx_pairs(observations)
    first = write_ecb_fx_parquet(
        pairs,
        tmp_path,
        request_url="https://data-api.ecb.europa.eu/service/data/EXR/fixture",
        response_sha256="a" * 64,
        currencies=required_ecb_currencies(),
        raw_observation_count=len(observations),
    )
    second = write_ecb_fx_parquet(
        pairs,
        tmp_path,
        request_url="https://data-api.ecb.europa.eu/service/data/EXR/fixture",
        response_sha256="a" * 64,
        currencies=required_ecb_currencies(),
        raw_observation_count=len(observations),
    )
    assert first == second
    assert Path(first.parquet_path).is_file()
    assert first.pair_observation_count == 16
