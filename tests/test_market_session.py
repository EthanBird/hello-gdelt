from datetime import date, datetime, time, timezone

import pytest

from hello_gdelt.market.session import (
    MarketSession,
    SessionLabel,
    align_news_timestamp,
    next_trading_date,
)


TRADING_DATES = (
    date(2026, 7, 16),
    date(2026, 7, 17),
    date(2026, 7, 20),
    date(2026, 7, 21),
)


def test_next_trading_date_respects_holidays_and_weekends() -> None:
    assert next_trading_date(date(2026, 7, 17), TRADING_DATES, include_candidate=True) == date(
        2026, 7, 17
    )
    assert next_trading_date(date(2026, 7, 17), TRADING_DATES, include_candidate=False) == date(
        2026, 7, 20
    )
    assert next_trading_date(date(2026, 7, 18), TRADING_DATES, include_candidate=True) == date(
        2026, 7, 20
    )


def test_tokyo_cash_session_uses_local_timezone() -> None:
    session = MarketSession(
        market_id="JPX",
        timezone_name="Asia/Tokyo",
        open_time=time(9, 0),
        close_time=time(15, 30),
        trading_dates=TRADING_DATES,
        calendar_version="test-v1",
    )
    # 23:30 UTC on the prior date is 08:30 JST: observable before the Tokyo open.
    assignment = align_news_timestamp(
        datetime(2026, 7, 16, 23, 30, tzinfo=timezone.utc), session
    )
    assert assignment.session_label == SessionLabel.PRE_MARKET
    assert assignment.effective_trading_date == date(2026, 7, 17)


def test_new_york_post_market_maps_to_next_registered_session() -> None:
    session = MarketSession(
        market_id="NYSE",
        timezone_name="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
        trading_dates=TRADING_DATES,
        calendar_version="test-v1",
    )
    assignment = align_news_timestamp(
        datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc), session
    )
    assert assignment.local_timestamp.hour == 17
    assert assignment.session_label == SessionLabel.POST_MARKET
    assert assignment.effective_trading_date == date(2026, 7, 20)


def test_weekend_news_maps_to_monday_without_fabricated_trading_day() -> None:
    session = MarketSession(
        market_id="SSE",
        timezone_name="Asia/Shanghai",
        open_time=time(9, 30),
        close_time=time(15, 0),
        trading_dates=TRADING_DATES,
        calendar_version="test-v1",
    )
    assignment = align_news_timestamp(
        datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc), session
    )
    assert assignment.session_label == SessionLabel.CLOSED
    assert assignment.effective_trading_date == date(2026, 7, 20)


def test_cme_overnight_open_uses_next_settlement_date() -> None:
    session = MarketSession(
        market_id="CME_ES",
        timezone_name="America/Chicago",
        open_time=time(17, 0),
        close_time=time(16, 0),
        trading_dates=TRADING_DATES,
        calendar_version="test-v1",
    )
    # 23:30 UTC is 18:30 CDT and belongs to the next settlement date.
    assignment = align_news_timestamp(
        datetime(2026, 7, 16, 23, 30, tzinfo=timezone.utc), session
    )
    assert assignment.session_label == SessionLabel.REGULAR
    assert assignment.effective_trading_date == date(2026, 7, 17)


def test_naive_timestamp_is_rejected() -> None:
    session = MarketSession(
        market_id="NYSE",
        timezone_name="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
        trading_dates=TRADING_DATES,
        calendar_version="test-v1",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        align_news_timestamp(datetime(2026, 7, 17, 12, 0), session)


def test_calendar_dates_must_be_sorted_and_unique() -> None:
    with pytest.raises(ValueError, match="sorted and unique"):
        MarketSession(
            market_id="BAD",
            timezone_name="UTC",
            open_time=time(9, 0),
            close_time=time(17, 0),
            trading_dates=(date(2026, 7, 20), date(2026, 7, 17)),
            calendar_version="test-v1",
        )
