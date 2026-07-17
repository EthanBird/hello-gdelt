from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SessionLabel = Literal[
    "PRE_OPEN",
    "IN_SESSION",
    "POST_CLOSE",
    "WEEKEND_HOLIDAY",
    "OUT_OF_CALENDAR",
]


class CalendarContractError(ValueError):
    """Raised when an explicit exchange session calendar is malformed."""


@dataclass(frozen=True, slots=True)
class MarketSession:
    trading_date: date
    open_utc: datetime
    close_utc: datetime
    exchange_timezone: str
    is_half_day: bool = False

    def __post_init__(self) -> None:
        if self.open_utc.tzinfo is None or self.close_utc.tzinfo is None:
            raise CalendarContractError("session boundaries must be timezone-aware")
        if self.open_utc.utcoffset() != timedelta(0) or self.close_utc.utcoffset() != timedelta(0):
            raise CalendarContractError("session boundaries must be normalized to UTC")
        if self.open_utc >= self.close_utc:
            raise CalendarContractError("session open must precede close")
        try:
            ZoneInfo(self.exchange_timezone)
        except ZoneInfoNotFoundError as exc:
            raise CalendarContractError(
                f"invalid exchange timezone: {self.exchange_timezone}"
            ) from exc


@dataclass(frozen=True, slots=True)
class SessionAssignment:
    timestamp_utc: datetime
    label: SessionLabel
    assigned_trading_date: date | None
    session_open_utc: datetime | None
    session_close_utc: datetime | None
    exchange_timezone: str


class StaticMarketCalendar:
    """Immutable point-in-time calendar built from explicit dated sessions.

    It does not infer holidays. The caller must provide every actual exchange session,
    including half days and exceptional closures, from an audited calendar source.
    """

    def __init__(self, sessions: tuple[MarketSession, ...]) -> None:
        if not sessions:
            raise CalendarContractError("calendar requires at least one session")
        ordered = tuple(sorted(sessions, key=lambda item: item.open_utc))
        timezones = {session.exchange_timezone for session in ordered}
        if len(timezones) != 1:
            raise CalendarContractError(
                f"all sessions must share one exchange timezone: {sorted(timezones)}"
            )
        trading_dates = [session.trading_date for session in ordered]
        if len(set(trading_dates)) != len(trading_dates):
            raise CalendarContractError("duplicate trading_date in static calendar")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.close_utc > current.open_utc:
                raise CalendarContractError(
                    f"overlapping sessions: {previous.trading_date} and {current.trading_date}"
                )
        self._sessions = ordered
        self.exchange_timezone = ordered[0].exchange_timezone
        self._zone = ZoneInfo(self.exchange_timezone)

    @property
    def sessions(self) -> tuple[MarketSession, ...]:
        return self._sessions

    @classmethod
    def from_local_times(
        cls,
        *,
        exchange_timezone: str,
        sessions: tuple[tuple[date, time, time, int, bool], ...],
    ) -> StaticMarketCalendar:
        """Create sessions from explicit local boundaries.

        Tuple fields are `(trading_date, open_time, close_time, open_day_offset,
        is_half_day)`. `open_day_offset=-1` supports overnight futures sessions.
        """

        try:
            zone = ZoneInfo(exchange_timezone)
        except ZoneInfoNotFoundError as exc:
            raise CalendarContractError(
                f"invalid exchange timezone: {exchange_timezone}"
            ) from exc
        materialized: list[MarketSession] = []
        for trading_date, open_time, close_time, open_day_offset, is_half_day in sessions:
            if open_day_offset not in {-1, 0}:
                raise CalendarContractError("open_day_offset must be -1 or 0")
            open_date = trading_date + timedelta(days=open_day_offset)
            local_open = datetime.combine(open_date, open_time, tzinfo=zone)
            local_close = datetime.combine(trading_date, close_time, tzinfo=zone)
            materialized.append(
                MarketSession(
                    trading_date=trading_date,
                    open_utc=local_open.astimezone(UTC),
                    close_utc=local_close.astimezone(UTC),
                    exchange_timezone=exchange_timezone,
                    is_half_day=is_half_day,
                )
            )
        return cls(tuple(materialized))

    def classify(self, timestamp_utc: datetime) -> SessionAssignment:
        if timestamp_utc.tzinfo is None:
            raise CalendarContractError("news timestamp must be timezone-aware")
        timestamp = timestamp_utc.astimezone(UTC)
        previous: MarketSession | None = None
        next_session: MarketSession | None = None
        for session in self._sessions:
            if session.open_utc <= timestamp < session.close_utc:
                return SessionAssignment(
                    timestamp_utc=timestamp,
                    label="IN_SESSION",
                    assigned_trading_date=session.trading_date,
                    session_open_utc=session.open_utc,
                    session_close_utc=session.close_utc,
                    exchange_timezone=self.exchange_timezone,
                )
            if session.close_utc <= timestamp:
                previous = session
                continue
            if timestamp < session.open_utc:
                next_session = session
                break

        if next_session is None:
            return SessionAssignment(
                timestamp_utc=timestamp,
                label="OUT_OF_CALENDAR",
                assigned_trading_date=None,
                session_open_utc=None,
                session_close_utc=None,
                exchange_timezone=self.exchange_timezone,
            )

        local_date = timestamp.astimezone(self._zone).date()
        if local_date == next_session.trading_date:
            label: SessionLabel = "PRE_OPEN"
        elif previous is not None and local_date == previous.trading_date:
            label = "POST_CLOSE"
        else:
            label = "WEEKEND_HOLIDAY"
        return SessionAssignment(
            timestamp_utc=timestamp,
            label=label,
            assigned_trading_date=next_session.trading_date,
            session_open_utc=next_session.open_utc,
            session_close_utc=next_session.close_utc,
            exchange_timezone=self.exchange_timezone,
        )
