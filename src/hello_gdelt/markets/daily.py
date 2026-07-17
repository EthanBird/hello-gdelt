from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal


class DailyMarketDataError(ValueError):
    """Raised when point-in-time daily market data violates the frozen contract."""


@dataclass(frozen=True, slots=True)
class DailyBar:
    asset_id: str
    trading_date: date
    session_open_utc: datetime
    session_close_utc: datetime
    available_at_utc: datetime
    currency: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    turnover: float | None
    price_adjustment_factor: float
    provider: str
    provider_series: str
    source_asof: str
    is_proxy: bool = False


@dataclass(frozen=True, slots=True)
class DailyReturn:
    asset_id: str
    trading_date: date
    horizon: int
    return_type: Literal["OVERNIGHT", "INTRADAY", "CLOSE_TO_CLOSE"]
    log_return: float
    simple_return: float
    available_at_utc: datetime
    start_trading_date: date
    end_trading_date: date


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise DailyMarketDataError(f"{field} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.utcoffset() is None:
        raise DailyMarketDataError(f"{field} has no UTC offset")
    return normalized


def validate_daily_bars(bars: tuple[DailyBar, ...]) -> tuple[DailyBar, ...]:
    if not bars:
        raise DailyMarketDataError("daily bar collection is empty")
    ordered = tuple(sorted(bars, key=lambda item: (item.asset_id, item.trading_date)))
    seen: set[tuple[str, date]] = set()
    previous_by_asset: dict[str, DailyBar] = {}
    for bar in ordered:
        if not bar.asset_id or not bar.provider or not bar.provider_series:
            raise DailyMarketDataError("asset_id, provider and provider_series are required")
        if len(bar.currency) != 3 or not bar.currency.isalpha():
            raise DailyMarketDataError(f"{bar.asset_id}: invalid currency {bar.currency!r}")
        identity = (bar.asset_id, bar.trading_date)
        if identity in seen:
            raise DailyMarketDataError(f"duplicate daily bar: {identity}")
        seen.add(identity)
        session_open = _utc(bar.session_open_utc, field="session_open_utc")
        session_close = _utc(bar.session_close_utc, field="session_close_utc")
        available = _utc(bar.available_at_utc, field="available_at_utc")
        if session_open >= session_close:
            raise DailyMarketDataError(f"{identity}: session open must precede close")
        if available < session_close:
            raise DailyMarketDataError(
                f"{identity}: bar cannot be available before the session closes"
            )
        prices = (bar.open, bar.high, bar.low, bar.close, bar.price_adjustment_factor)
        if any(not math.isfinite(value) or value <= 0 for value in prices):
            raise DailyMarketDataError(f"{identity}: prices and adjustment factor must be positive")
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise DailyMarketDataError(f"{identity}: OHLC range is inconsistent")
        if bar.high < bar.low:
            raise DailyMarketDataError(f"{identity}: high is below low")
        for field, value in (("volume", bar.volume), ("turnover", bar.turnover)):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise DailyMarketDataError(f"{identity}: {field} must be finite and non-negative")
        previous = previous_by_asset.get(bar.asset_id)
        if previous is not None:
            if bar.trading_date <= previous.trading_date:
                raise DailyMarketDataError(f"{bar.asset_id}: trading dates are not increasing")
            if session_open <= previous.session_close_utc.astimezone(UTC):
                raise DailyMarketDataError(f"{bar.asset_id}: daily sessions overlap")
        previous_by_asset[bar.asset_id] = bar
    return ordered


def _adjusted(price: float, factor: float) -> float:
    value = price * factor
    if not math.isfinite(value) or value <= 0:
        raise DailyMarketDataError("adjusted price is not positive and finite")
    return value


def _return(
    *,
    asset_id: str,
    trading_date: date,
    horizon: int,
    return_type: Literal["OVERNIGHT", "INTRADAY", "CLOSE_TO_CLOSE"],
    start_price: float,
    end_price: float,
    available_at_utc: datetime,
    start_trading_date: date,
    end_trading_date: date,
) -> DailyReturn:
    ratio = end_price / start_price
    return DailyReturn(
        asset_id=asset_id,
        trading_date=trading_date,
        horizon=horizon,
        return_type=return_type,
        log_return=math.log(ratio),
        simple_return=ratio - 1.0,
        available_at_utc=available_at_utc,
        start_trading_date=start_trading_date,
        end_trading_date=end_trading_date,
    )


def compute_daily_returns(
    bars: tuple[DailyBar, ...],
    *,
    horizons: tuple[int, ...] = (1, 2, 5, 10, 20),
    as_of_utc: datetime | None = None,
) -> tuple[DailyReturn, ...]:
    """Compute point-in-time adjusted returns without using unavailable bars.

    `price_adjustment_factor` is a provider-supplied point-in-time multiplier applied
    to all OHLC values. A future-revised total-return factor is not permitted.
    """

    ordered = validate_daily_bars(bars)
    normalized_horizons = tuple(sorted(set(horizons)))
    if not normalized_horizons or any(item <= 0 for item in normalized_horizons):
        raise DailyMarketDataError("return horizons must be positive integers")
    cutoff = None if as_of_utc is None else _utc(as_of_utc, field="as_of_utc")
    by_asset: dict[str, list[DailyBar]] = {}
    for bar in ordered:
        if cutoff is not None and bar.available_at_utc.astimezone(UTC) > cutoff:
            continue
        by_asset.setdefault(bar.asset_id, []).append(bar)

    returns: list[DailyReturn] = []
    for asset_id, asset_bars in by_asset.items():
        for index, bar in enumerate(asset_bars):
            adjusted_open = _adjusted(bar.open, bar.price_adjustment_factor)
            adjusted_close = _adjusted(bar.close, bar.price_adjustment_factor)
            returns.append(
                _return(
                    asset_id=asset_id,
                    trading_date=bar.trading_date,
                    horizon=0,
                    return_type="INTRADAY",
                    start_price=adjusted_open,
                    end_price=adjusted_close,
                    available_at_utc=bar.available_at_utc.astimezone(UTC),
                    start_trading_date=bar.trading_date,
                    end_trading_date=bar.trading_date,
                )
            )
            if index > 0:
                previous = asset_bars[index - 1]
                previous_close = _adjusted(
                    previous.close,
                    previous.price_adjustment_factor,
                )
                returns.append(
                    _return(
                        asset_id=asset_id,
                        trading_date=bar.trading_date,
                        horizon=0,
                        return_type="OVERNIGHT",
                        start_price=previous_close,
                        end_price=adjusted_open,
                        available_at_utc=bar.available_at_utc.astimezone(UTC),
                        start_trading_date=previous.trading_date,
                        end_trading_date=bar.trading_date,
                    )
                )
            for horizon in normalized_horizons:
                end_index = index + horizon
                if end_index >= len(asset_bars):
                    continue
                end_bar = asset_bars[end_index]
                end_close = _adjusted(
                    end_bar.close,
                    end_bar.price_adjustment_factor,
                )
                returns.append(
                    _return(
                        asset_id=asset_id,
                        trading_date=bar.trading_date,
                        horizon=horizon,
                        return_type="CLOSE_TO_CLOSE",
                        start_price=adjusted_close,
                        end_price=end_close,
                        available_at_utc=end_bar.available_at_utc.astimezone(UTC),
                        start_trading_date=bar.trading_date,
                        end_trading_date=end_bar.trading_date,
                    )
                )
    return tuple(
        sorted(
            returns,
            key=lambda item: (
                item.asset_id,
                item.trading_date,
                item.return_type,
                item.horizon,
            ),
        )
    )
