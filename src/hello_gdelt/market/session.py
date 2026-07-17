from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo


class SessionLabel(StrEnum):
    """Where a news timestamp falls relative to a market's trading session."""

    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    POST_MARKET = "post_market"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class MarketSession:
    """A versionable market-session rule.

    ``trading_dates`` are the actual exchange trading or settlement dates available at
    the point in time of an experiment. Supplying them explicitly avoids silently
    treating weekends or future holiday calendars as trading days.

    An overnight session is represented by ``open_time > close_time``. For example,
    CME 17:00--16:00 is assigned to the next settlement date after the evening open.
    """

    market_id: str
    timezone_name: str
    open_time: time
    close_time: time
    trading_dates: tuple[date, ...]
    calendar_version: str
    valid_from: date | None = None
    valid_to: date | None = None

    def __post_init__(self) -> None:
        if not self.market_id.strip():
            raise ValueError("market_id must not be empty")
        if not self.calendar_version.strip():
            raise ValueError("calendar_version must not be empty")
        if tuple(sorted(set(self.trading_dates))) != self.trading_dates:
            raise ValueError("trading_dates must be sorted and unique")
        if not self.trading_dates:
            raise ValueError("trading_dates must not be empty")
        ZoneInfo(self.timezone_name)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def crosses_midnight(self) -> bool:
        return self.open_time > self.close_time


@dataclass(frozen=True, slots=True)
class SessionAssignment:
    market_id: str
    source_timestamp_utc: datetime
    local_timestamp: datetime
    session_label: SessionLabel
    effective_trading_date: date | None
    calendar_version: str


def _ensure_aware_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("news timestamp must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def next_trading_date(
    candidate: date,
    trading_dates: tuple[date, ...],
    *,
    include_candidate: bool,
) -> date | None:
    """Return the first registered trading date on or after/after ``candidate``."""

    index = (
        bisect_left(trading_dates, candidate)
        if include_candidate
        else bisect_right(trading_dates, candidate)
    )
    return trading_dates[index] if index < len(trading_dates) else None


def _within_validity(session: MarketSession, local_date: date) -> None:
    if session.valid_from is not None and local_date < session.valid_from:
        raise ValueError("timestamp predates this calendar version")
    if session.valid_to is not None and local_date > session.valid_to:
        raise ValueError("timestamp exceeds this calendar version")


def _align_day_session(local: datetime, session: MarketSession) -> tuple[SessionLabel, date | None]:
    local_date = local.date()
    local_time = local.timetz().replace(tzinfo=None)
    is_trading_day = local_date in session.trading_dates

    if is_trading_day and local_time < session.open_time:
        return SessionLabel.PRE_MARKET, local_date
    if is_trading_day and session.open_time <= local_time < session.close_time:
        return SessionLabel.REGULAR, local_date
    if is_trading_day and local_time >= session.close_time:
        return (
            SessionLabel.POST_MARKET,
            next_trading_date(local_date, session.trading_dates, include_candidate=False),
        )
    return (
        SessionLabel.CLOSED,
        next_trading_date(local_date, session.trading_dates, include_candidate=True),
    )


def _align_overnight_session(
    local: datetime, session: MarketSession
) -> tuple[SessionLabel, date | None]:
    local_date = local.date()
    local_time = local.timetz().replace(tzinfo=None)

    if local_time >= session.open_time:
        settlement_candidate = local_date + timedelta(days=1)
        effective = next_trading_date(
            settlement_candidate, session.trading_dates, include_candidate=True
        )
        return (
            (SessionLabel.REGULAR if effective == settlement_candidate else SessionLabel.CLOSED),
            effective,
        )

    if local_time < session.close_time:
        effective = next_trading_date(local_date, session.trading_dates, include_candidate=True)
        return (
            (SessionLabel.REGULAR if effective == local_date else SessionLabel.CLOSED),
            effective,
        )

    # The maintenance interval between close and the next evening open.
    return (
        SessionLabel.CLOSED,
        next_trading_date(local_date, session.trading_dates, include_candidate=False),
    )


def align_news_timestamp(timestamp: datetime, session: MarketSession) -> SessionAssignment:
    """Assign a news timestamp to the earliest market session able to observe it.

    The function is deterministic and makes no assumption that every weekday is a
    trading day. Day sessions distinguish pre-market, regular, post-market and closed
    periods. Overnight sessions use the exchange settlement date.
    """

    timestamp_utc = _ensure_aware_utc(timestamp)
    local = timestamp_utc.astimezone(session.timezone)
    _within_validity(session, local.date())
    if session.crosses_midnight:
        label, effective_date = _align_overnight_session(local, session)
    else:
        label, effective_date = _align_day_session(local, session)
    return SessionAssignment(
        market_id=session.market_id,
        source_timestamp_utc=timestamp_utc,
        local_timestamp=local,
        session_label=label,
        effective_trading_date=effective_date,
        calendar_version=session.calendar_version,
    )
