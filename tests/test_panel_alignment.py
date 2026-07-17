from datetime import UTC, date, datetime, time, timedelta

import pytest

from hello_gdelt.markets.calendar import StaticMarketCalendar
from hello_gdelt.markets.daily import DailyBar, compute_daily_returns
from hello_gdelt.research.panel import (
    NewsFeatureObservation,
    PanelAlignmentError,
    aggregate_news_to_sessions,
    align_session_features_to_returns,
)


def calendar() -> StaticMarketCalendar:
    return StaticMarketCalendar.from_local_times(
        exchange_timezone="Asia/Shanghai",
        sessions=(
            (date(2026, 7, 16), time(9, 30), time(15, 0), 0, False),
            (date(2026, 7, 17), time(9, 30), time(15, 0), 0, False),
        ),
    )


def bar(trading_date: date, open_price: float, close_price: float) -> DailyBar:
    session_open = datetime(
        trading_date.year,
        trading_date.month,
        trading_date.day,
        1,
        30,
        tzinfo=UTC,
    )
    session_close = datetime(
        trading_date.year,
        trading_date.month,
        trading_date.day,
        7,
        0,
        tzinfo=UTC,
    )
    available = session_close + timedelta(minutes=5)
    return DailyBar(
        asset_id="CHN_CSI300",
        trading_date=trading_date,
        session_open_utc=session_open,
        session_close_utc=session_close,
        available_at_utc=available,
        currency="CNY",
        open=open_price,
        high=max(open_price, close_price) * 1.01,
        low=min(open_price, close_price) * 0.99,
        close=close_price,
        volume=1_000_000.0,
        turnover=100_000_000.0,
        price_adjustment_factor=1.0,
        adjustment_available_at_utc=available,
        provider="FIXTURE",
        provider_series="CSI300",
        source_asof="fixture-v1",
    )


def feature(
    available_at_utc: datetime,
    *,
    value: float,
    source_timestamp: str,
    observed_at_utc: datetime | None = None,
) -> NewsFeatureObservation:
    return NewsFeatureObservation(
        market_group="A_SHARE",
        feature_name="attention_z",
        observed_at_utc=observed_at_utc or available_at_utc,
        available_at_utc=available_at_utc,
        value=value,
        source_timestamp=source_timestamp,
    )


def test_pre_open_news_predicts_intraday_without_leakage() -> None:
    observations = (
        feature(
            datetime(2026, 7, 17, 1, 0, tzinfo=UTC),
            value=2.0,
            source_timestamp="20260717010000",
        ),
        feature(
            datetime(2026, 7, 17, 1, 15, tzinfo=UTC),
            value=4.0,
            source_timestamp="20260717011500",
        ),
    )
    features = aggregate_news_to_sessions(
        observations,
        market_group="A_SHARE",
        calendar=calendar(),
    )
    bars = (bar(date(2026, 7, 17), 100.0, 102.0),)
    returns = compute_daily_returns(bars, horizons=(1,))
    panel = align_session_features_to_returns(
        features,
        returns,
        bars,
        asset_market_groups={"CHN_CSI300": "A_SHARE"},
        alignment_mode="PREDICTIVE",
    )
    assert len(panel) == 1
    assert panel[0].session_label == "PRE_OPEN"
    assert panel[0].exposure_value == pytest.approx(6.0)
    assert panel[0].exposure_count == 2
    assert panel[0].outcome_type == "INTRADAY"
    assert panel[0].exposure_available_at_utc <= panel[0].outcome_start_utc


def test_in_session_news_is_not_mislabeled_as_predictive() -> None:
    observations = (
        feature(
            datetime(2026, 7, 17, 2, 0, tzinfo=UTC),
            value=3.0,
            source_timestamp="20260717020000",
        ),
    )
    features = aggregate_news_to_sessions(
        observations,
        market_group="A_SHARE",
        calendar=calendar(),
    )
    bars = (bar(date(2026, 7, 17), 100.0, 102.0),)
    returns = compute_daily_returns(bars, horizons=(1,))
    predictive = align_session_features_to_returns(
        features,
        returns,
        bars,
        asset_market_groups={"CHN_CSI300": "A_SHARE"},
        alignment_mode="PREDICTIVE",
    )
    event_window = align_session_features_to_returns(
        features,
        returns,
        bars,
        asset_market_groups={"CHN_CSI300": "A_SHARE"},
        alignment_mode="EVENT_WINDOW",
    )
    assert predictive == ()
    assert len(event_window) == 1
    assert event_window[0].session_label == "IN_SESSION"
    assert event_window[0].alignment_mode == "EVENT_WINDOW"


def test_post_close_news_is_an_overnight_event_window_not_a_forecast() -> None:
    observations = (
        feature(
            datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            value=-2.0,
            source_timestamp="20260716080000",
        ),
    )
    features = aggregate_news_to_sessions(
        observations,
        market_group="A_SHARE",
        calendar=calendar(),
    )
    bars = (
        bar(date(2026, 7, 16), 100.0, 101.0),
        bar(date(2026, 7, 17), 102.0, 103.0),
    )
    returns = compute_daily_returns(bars, horizons=(1,))
    predictive = align_session_features_to_returns(
        features,
        returns,
        bars,
        asset_market_groups={"CHN_CSI300": "A_SHARE"},
        alignment_mode="PREDICTIVE",
    )
    event_window = align_session_features_to_returns(
        features,
        returns,
        bars,
        asset_market_groups={"CHN_CSI300": "A_SHARE"},
        alignment_mode="EVENT_WINDOW",
    )
    overnight_event = next(
        item for item in event_window if item.outcome_type == "OVERNIGHT"
    )
    assert all(item.outcome_type != "OVERNIGHT" for item in predictive)
    assert overnight_event.session_label == "POST_CLOSE"
    assert overnight_event.outcome_start_utc < overnight_event.exposure_available_at_utc
    assert overnight_event.exposure_available_at_utc <= overnight_event.outcome_end_utc


def test_feature_availability_cannot_precede_observation() -> None:
    observations = (
        feature(
            datetime(2026, 7, 17, 1, 0, tzinfo=UTC),
            observed_at_utc=datetime(2026, 7, 17, 1, 15, tzinfo=UTC),
            value=1.0,
            source_timestamp="20260717011500",
        ),
    )
    with pytest.raises(PanelAlignmentError, match="available before"):
        aggregate_news_to_sessions(
            observations,
            market_group="A_SHARE",
            calendar=calendar(),
        )
