from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from hello_gdelt.markets.daily import (
    DailyBar,
    DailyMarketDataError,
    compute_daily_returns,
    validate_daily_bars,
)


def bar(
    trading_date: date,
    *,
    open_price: float,
    close_price: float,
    factor: float = 1.0,
    available_delay_minutes: int = 5,
) -> DailyBar:
    session_open = datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)
    session_close = session_open + timedelta(hours=6)
    return DailyBar(
        asset_id="TEST_ASSET",
        trading_date=trading_date,
        session_open_utc=session_open,
        session_close_utc=session_close,
        available_at_utc=session_close + timedelta(minutes=available_delay_minutes),
        currency="USD",
        open=open_price,
        high=max(open_price, close_price) * 1.01,
        low=min(open_price, close_price) * 0.99,
        close=close_price,
        volume=1000.0,
        turnover=100_000.0,
        price_adjustment_factor=factor,
        provider="FIXTURE",
        provider_series="TEST",
        source_asof="fixture-v1",
    )


def test_daily_bar_validation_rejects_pre_close_availability() -> None:
    item = bar(
        date(2026, 7, 16),
        open_price=100.0,
        close_price=101.0,
        available_delay_minutes=-1,
    )
    with pytest.raises(DailyMarketDataError, match="cannot be available before"):
        validate_daily_bars((item,))


def test_daily_bar_validation_rejects_inconsistent_ohlc() -> None:
    item = bar(date(2026, 7, 16), open_price=100.0, close_price=101.0)
    invalid = replace(item, high=99.0)
    with pytest.raises(DailyMarketDataError, match="OHLC range is inconsistent"):
        validate_daily_bars((invalid,))


def test_adjustment_factor_removes_mechanical_split_return() -> None:
    bars = (
        bar(date(2026, 7, 15), open_price=98.0, close_price=100.0, factor=0.5),
        bar(date(2026, 7, 16), open_price=50.0, close_price=51.0, factor=1.0),
    )
    returns = compute_daily_returns(bars, horizons=(1,))
    overnight = next(
        item
        for item in returns
        if item.trading_date == date(2026, 7, 16) and item.return_type == "OVERNIGHT"
    )
    close_to_close = next(
        item
        for item in returns
        if item.trading_date == date(2026, 7, 15)
        and item.return_type == "CLOSE_TO_CLOSE"
        and item.horizon == 1
    )
    assert overnight.simple_return == pytest.approx(0.0)
    assert close_to_close.simple_return == pytest.approx(0.02)


def test_as_of_cutoff_excludes_unavailable_future_bar_and_return() -> None:
    first = bar(date(2026, 7, 15), open_price=100.0, close_price=101.0)
    second = bar(date(2026, 7, 16), open_price=102.0, close_price=103.0)
    cutoff = first.available_at_utc
    returns = compute_daily_returns((first, second), horizons=(1,), as_of_utc=cutoff)
    assert all(item.end_trading_date == date(2026, 7, 15) for item in returns)
    assert all(item.return_type == "INTRADAY" for item in returns)


def test_duplicate_asset_date_is_rejected() -> None:
    item = bar(date(2026, 7, 16), open_price=100.0, close_price=101.0)
    with pytest.raises(DailyMarketDataError, match="duplicate daily bar"):
        validate_daily_bars((item, item))
