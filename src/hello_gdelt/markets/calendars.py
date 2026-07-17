from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo


class SessionLabel(StrEnum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    POST_MARKET = "post_market"
    MAINTENANCE = "maintenance"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SessionOverride:
    trading_date: date
    closed: bool = False
    open_time: time | None = None
    close_time: time | None = None

    def __post_init__(self) -> None:
        if self.closed and (self.open_time is not None or self.close_time is not None):
            raise ValueError("closed overrides cannot define open or close times")
        if (self.open_time is None) != (self.close_time is None):
            raise ValueError("open_time and close_time must be provided together")


@dataclass(frozen=True, slots=True)
class TimestampAlignment:
    calendar_id: str
    source_timestamp_utc: datetime
    local_timestamp: datetime
    observed_session: SessionLabel
    reaction_trading_date: date
    session_open_utc: datetime
    session_close_utc: datetime


@dataclass(frozen=True, slots=True)
class MarketCalendar:
    """Deterministic exchange-session calendar with explicit holiday snapshots.

    ``session_open_day_offset=-1`` models sessions such as CME Globex that open on
    the calendar day before their labelled trading date. Holidays and special
    sessions are deliberately supplied as immutable snapshots so historical
    experiments can pin the exact calendar version used.
    """

    calendar_id: str
    timezone_name: str
    regular_open: time
    regular_close: time
    session_open_day_offset: int = 0
    pre_market_open: time | None = None
    post_market_close: time | None = None
    weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    holidays: frozenset[date] = frozenset()
    overrides: tuple[SessionOverride, ...] = ()
    version: str = "unversioned"

    def __post_init__(self) -> None:
        if self.session_open_day_offset not in {-1, 0}:
            raise ValueError("session_open_day_offset must be -1 or 0")
        if not self.calendar_id:
            raise ValueError("calendar_id is required")
        ZoneInfo(self.timezone_name)
        override_dates = [item.trading_date for item in self.overrides]
        if len(override_dates) != len(set(override_dates)):
            raise ValueError("overrides must contain unique trading dates")

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def override_map(self) -> Mapping[date, SessionOverride]:
        return MappingProxyType({item.trading_date: item for item in self.overrides})

    def is_trading_day(self, value: date) -> bool:
        override = self.override_map.get(value)
        if override is not None:
            return not override.closed
        return value.weekday() in self.weekdays and value not in self.holidays

    def next_trading_day(self, value: date, *, include_current: bool = False) -> date:
        candidate = value if include_current else value + timedelta(days=1)
        for _ in range(370):
            if self.is_trading_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        raise RuntimeError("no trading day found within 370 days")

    def previous_trading_day(self, value: date, *, include_current: bool = False) -> date:
        candidate = value if include_current else value - timedelta(days=1)
        for _ in range(370):
            if self.is_trading_day(candidate):
                return candidate
            candidate -= timedelta(days=1)
        raise RuntimeError("no trading day found within 370 days")

    def session_bounds_local(self, trading_date: date) -> tuple[datetime, datetime]:
        if not self.is_trading_day(trading_date):
            raise ValueError(f"{trading_date.isoformat()} is not a trading day")
        override = self.override_map.get(trading_date)
        open_value = override.open_time if override and override.open_time else self.regular_open
        close_value = override.close_time if override and override.close_time else self.regular_close
        open_date = trading_date + timedelta(days=self.session_open_day_offset)
        open_dt = datetime.combine(open_date, open_value, self.timezone)
        close_dt = datetime.combine(trading_date, close_value, self.timezone)
        if close_dt <= open_dt:
            raise ValueError("session close must be after session open")
        return open_dt, close_dt

    def _regular_trading_date(self, local_timestamp: datetime) -> date | None:
        candidates = (local_timestamp.date(), local_timestamp.date() + timedelta(days=1))
        for trading_date in candidates:
            if not self.is_trading_day(trading_date):
                continue
            open_dt, close_dt = self.session_bounds_local(trading_date)
            if open_dt <= local_timestamp < close_dt:
                return trading_date
        return None

    def _next_session(self, local_timestamp: datetime) -> tuple[date, datetime, datetime]:
        start_date = local_timestamp.date()
        for offset in range(0, 370):
            trading_date = start_date + timedelta(days=offset)
            if not self.is_trading_day(trading_date):
                continue
            open_dt, close_dt = self.session_bounds_local(trading_date)
            if open_dt >= local_timestamp:
                return trading_date, open_dt, close_dt
        raise RuntimeError("no future session found within 370 days")

    def classify(self, timestamp: datetime) -> SessionLabel:
        utc_timestamp = _as_utc(timestamp)
        local_timestamp = utc_timestamp.astimezone(self.timezone)
        if self._regular_trading_date(local_timestamp) is not None:
            return SessionLabel.REGULAR

        local_date = local_timestamp.date()
        if self.session_open_day_offset == 0 and self.is_trading_day(local_date):
            open_dt, close_dt = self.session_bounds_local(local_date)
            if self.pre_market_open is not None:
                pre_dt = datetime.combine(local_date, self.pre_market_open, self.timezone)
                if pre_dt <= local_timestamp < open_dt:
                    return SessionLabel.PRE_MARKET
            if self.post_market_close is not None:
                post_dt = datetime.combine(local_date, self.post_market_close, self.timezone)
                if close_dt <= local_timestamp < post_dt:
                    return SessionLabel.POST_MARKET

        if self.session_open_day_offset == -1:
            next_date = local_date + timedelta(days=1)
            if self.is_trading_day(next_date):
                next_open, _ = self.session_bounds_local(next_date)
                prior_date = self.previous_trading_day(next_date)
                _, prior_close = self.session_bounds_local(prior_date)
                if prior_close <= local_timestamp < next_open:
                    return SessionLabel.MAINTENANCE
        return SessionLabel.CLOSED

    def align_news_timestamp(self, timestamp: datetime) -> TimestampAlignment:
        utc_timestamp = _as_utc(timestamp)
        local_timestamp = utc_timestamp.astimezone(self.timezone)
        regular_date = self._regular_trading_date(local_timestamp)
        observed = self.classify(utc_timestamp)

        if regular_date is not None:
            trading_date = regular_date
            open_dt, close_dt = self.session_bounds_local(trading_date)
        elif (
            observed is SessionLabel.PRE_MARKET
            and self.session_open_day_offset == 0
            and self.is_trading_day(local_timestamp.date())
        ):
            trading_date = local_timestamp.date()
            open_dt, close_dt = self.session_bounds_local(trading_date)
        else:
            trading_date, open_dt, close_dt = self._next_session(local_timestamp)

        return TimestampAlignment(
            calendar_id=self.calendar_id,
            source_timestamp_utc=utc_timestamp,
            local_timestamp=local_timestamp,
            observed_session=observed,
            reaction_trading_date=trading_date,
            session_open_utc=open_dt.astimezone(timezone.utc),
            session_close_utc=close_dt.astimezone(timezone.utc),
        )


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


MARKET_CALENDARS: Mapping[str, MarketCalendar] = MappingProxyType(
    {
        "XSHG": MarketCalendar(
            calendar_id="XSHG",
            timezone_name="Asia/Shanghai",
            regular_open=time(9, 30),
            regular_close=time(15, 0),
            pre_market_open=time(9, 15),
            version="framework-v1",
        ),
        "XKRX": MarketCalendar(
            calendar_id="XKRX",
            timezone_name="Asia/Seoul",
            regular_open=time(9, 0),
            regular_close=time(15, 30),
            pre_market_open=time(8, 30),
            version="framework-v1",
        ),
        "XJPX": MarketCalendar(
            calendar_id="XJPX",
            timezone_name="Asia/Tokyo",
            regular_open=time(9, 0),
            regular_close=time(15, 30),
            pre_market_open=time(8, 0),
            version="framework-v1",
        ),
        "XNYS": MarketCalendar(
            calendar_id="XNYS",
            timezone_name="America/New_York",
            regular_open=time(9, 30),
            regular_close=time(16, 0),
            pre_market_open=time(4, 0),
            post_market_close=time(20, 0),
            version="framework-v1",
        ),
        "XCME": MarketCalendar(
            calendar_id="XCME",
            timezone_name="America/Chicago",
            regular_open=time(18, 0),
            regular_close=time(17, 0),
            session_open_day_offset=-1,
            version="framework-v1",
        ),
        "XLON": MarketCalendar(
            calendar_id="XLON",
            timezone_name="Europe/London",
            regular_open=time(8, 0),
            regular_close=time(16, 30),
            pre_market_open=time(7, 0),
            version="framework-v1",
        ),
    }
)


def get_market_calendar(calendar_id: str) -> MarketCalendar:
    try:
        return MARKET_CALENDARS[calendar_id]
    except KeyError as exc:
        raise KeyError(f"unknown market calendar: {calendar_id}") from exc
