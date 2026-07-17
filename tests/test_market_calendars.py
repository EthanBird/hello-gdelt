from datetime import date, datetime, time, timezone

import pytest

from hello_gdelt.markets.calendars import (
    MarketCalendar,
    SessionLabel,
    SessionOverride,
    get_market_calendar,
)


def test_rejects_naive_timestamp() -> None:
    calendar = get_market_calendar("XNYS")
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar.align_news_timestamp(datetime(2026, 7, 17, 13, 30))


def test_nyse_dst_alignment_is_regular_session() -> None:
    calendar = get_market_calendar("XNYS")
    aligned = calendar.align_news_timestamp(datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc))
    assert aligned.local_timestamp.hour == 9
    assert aligned.local_timestamp.minute == 30
    assert aligned.observed_session is SessionLabel.REGULAR
    assert aligned.reaction_trading_date == date(2026, 3, 9)


def test_sse_pre_market_news_reacts_same_trading_day() -> None:
    calendar = get_market_calendar("XSHG")
    aligned = calendar.align_news_timestamp(datetime(2026, 7, 20, 1, 20, tzinfo=timezone.utc))
    assert aligned.observed_session is SessionLabel.PRE_MARKET
    assert aligned.reaction_trading_date == date(2026, 7, 20)
    assert aligned.session_open_utc == datetime(2026, 7, 20, 1, 30, tzinfo=timezone.utc)


def test_nyse_post_market_friday_reacts_monday() -> None:
    calendar = get_market_calendar("XNYS")
    aligned = calendar.align_news_timestamp(datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc))
    assert aligned.observed_session is SessionLabel.POST_MARKET
    assert aligned.reaction_trading_date == date(2026, 7, 20)


def test_cme_sunday_open_is_labelled_monday_session() -> None:
    calendar = get_market_calendar("XCME")
    aligned = calendar.align_news_timestamp(datetime(2026, 7, 19, 23, 30, tzinfo=timezone.utc))
    assert aligned.observed_session is SessionLabel.REGULAR
    assert aligned.reaction_trading_date == date(2026, 7, 20)


def test_cme_maintenance_aligns_to_next_open() -> None:
    calendar = get_market_calendar("XCME")
    aligned = calendar.align_news_timestamp(datetime(2026, 7, 20, 22, 30, tzinfo=timezone.utc))
    assert aligned.observed_session is SessionLabel.MAINTENANCE
    assert aligned.reaction_trading_date == date(2026, 7, 21)
    assert aligned.session_open_utc == datetime(2026, 7, 20, 23, 0, tzinfo=timezone.utc)


def test_explicit_holiday_snapshot_and_early_close() -> None:
    calendar = MarketCalendar(
        calendar_id="TEST",
        timezone_name="UTC",
        regular_open=time(9),
        regular_close=time(17),
        holidays=frozenset({date(2026, 1, 1)}),
        overrides=(SessionOverride(date(2026, 1, 2), open_time=time(9), close_time=time(13)),),
        version="test-v1",
    )
    assert not calendar.is_trading_day(date(2026, 1, 1))
    open_dt, close_dt = calendar.session_bounds_local(date(2026, 1, 2))
    assert open_dt.hour == 9
    assert close_dt.hour == 13


def test_sse_midday_break_reacts_at_afternoon_reopen() -> None:
    calendar = get_market_calendar("XSHG")
    aligned = calendar.align_news_timestamp(datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc))
    assert aligned.observed_session is SessionLabel.MIDDAY_BREAK
    assert aligned.reaction_trading_date == date(2026, 7, 20)
    assert aligned.reaction_start_utc == datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)


def test_cme_weekend_is_closed_not_maintenance() -> None:
    calendar = get_market_calendar("XCME")
    observed = calendar.classify(datetime(2026, 7, 18, 18, 0, tzinfo=timezone.utc))
    assert observed is SessionLabel.CLOSED
