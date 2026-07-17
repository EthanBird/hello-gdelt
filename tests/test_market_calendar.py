from datetime import UTC, date, datetime, time

import pytest

from hello_gdelt.markets.calendar import CalendarContractError, StaticMarketCalendar


def shanghai_calendar() -> StaticMarketCalendar:
    return StaticMarketCalendar.from_local_times(
        exchange_timezone="Asia/Shanghai",
        sessions=(
            (date(2026, 7, 17), time(9, 30), time(15, 0), 0, False),
            (date(2026, 7, 20), time(9, 30), time(15, 0), 0, False),
        ),
    )


def test_stock_session_labels_pre_open_in_session_post_close_and_weekend() -> None:
    calendar = shanghai_calendar()
    pre = calendar.classify(datetime(2026, 7, 17, 0, 0, tzinfo=UTC))
    inside = calendar.classify(datetime(2026, 7, 17, 2, 0, tzinfo=UTC))
    post = calendar.classify(datetime(2026, 7, 17, 8, 0, tzinfo=UTC))
    weekend = calendar.classify(datetime(2026, 7, 18, 4, 0, tzinfo=UTC))
    assert pre.label == "PRE_OPEN"
    assert pre.assigned_trading_date == date(2026, 7, 17)
    assert inside.label == "IN_SESSION"
    assert inside.assigned_trading_date == date(2026, 7, 17)
    assert post.label == "POST_CLOSE"
    assert post.assigned_trading_date == date(2026, 7, 20)
    assert weekend.label == "WEEKEND_HOLIDAY"
    assert weekend.assigned_trading_date == date(2026, 7, 20)


def test_new_york_calendar_applies_dst_per_dated_session() -> None:
    calendar = StaticMarketCalendar.from_local_times(
        exchange_timezone="America/New_York",
        sessions=(
            (date(2026, 3, 6), time(9, 30), time(16, 0), 0, False),
            (date(2026, 3, 9), time(9, 30), time(16, 0), 0, False),
        ),
    )
    friday, monday = calendar.sessions
    assert friday.open_utc == datetime(2026, 3, 6, 14, 30, tzinfo=UTC)
    assert monday.open_utc == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)


def test_overnight_futures_session_maps_sunday_open_to_monday_trading_date() -> None:
    calendar = StaticMarketCalendar.from_local_times(
        exchange_timezone="America/Chicago",
        sessions=(
            (date(2026, 3, 9), time(17, 0), time(16, 0), -1, False),
            (date(2026, 3, 10), time(17, 0), time(16, 0), -1, False),
        ),
    )
    assignment = calendar.classify(datetime(2026, 3, 8, 23, 30, tzinfo=UTC))
    assert assignment.label == "IN_SESSION"
    assert assignment.assigned_trading_date == date(2026, 3, 9)


def test_exact_close_is_post_close_for_the_next_session() -> None:
    calendar = shanghai_calendar()
    assignment = calendar.classify(datetime(2026, 7, 17, 7, 0, tzinfo=UTC))
    assert assignment.label == "POST_CLOSE"
    assert assignment.assigned_trading_date == date(2026, 7, 20)


def test_out_of_calendar_after_last_known_session_is_explicit() -> None:
    calendar = shanghai_calendar()
    assignment = calendar.classify(datetime(2026, 7, 21, 0, 0, tzinfo=UTC))
    assert assignment.label == "OUT_OF_CALENDAR"
    assert assignment.assigned_trading_date is None


def test_calendar_rejects_overlapping_sessions() -> None:
    with pytest.raises(CalendarContractError, match="overlapping sessions"):
        StaticMarketCalendar.from_local_times(
            exchange_timezone="UTC",
            sessions=(
                (date(2026, 7, 17), time(9, 0), time(17, 0), 0, False),
                (date(2026, 7, 18), time(16, 0), time(18, 0), -1, False),
            ),
        )


def test_calendar_rejects_naive_news_timestamp() -> None:
    with pytest.raises(CalendarContractError, match="timezone-aware"):
        shanghai_calendar().classify(datetime(2026, 7, 17, 2, 0))
