from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from hello_gdelt.markets.calendar import SessionLabel, StaticMarketCalendar
from hello_gdelt.markets.daily import DailyBar, DailyReturn, validate_daily_bars

AlignmentMode = Literal["PREDICTIVE", "EVENT_WINDOW"]


class PanelAlignmentError(ValueError):
    """Raised when news and market outcomes cannot be aligned without leakage."""


@dataclass(frozen=True, slots=True)
class NewsFeatureObservation:
    market_group: str
    feature_name: str
    observed_at_utc: datetime
    available_at_utc: datetime
    value: float
    source_timestamp: str


@dataclass(frozen=True, slots=True)
class SessionNewsFeature:
    market_group: str
    trading_date: date
    session_label: SessionLabel
    feature_name: str
    observation_count: int
    value_sum: float
    value_mean: float
    first_available_at_utc: datetime
    last_available_at_utc: datetime
    source_timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlignedPanelObservation:
    asset_id: str
    market_group: str
    trading_date: date
    session_label: SessionLabel
    feature_name: str
    exposure_value: float
    exposure_count: int
    exposure_available_at_utc: datetime
    outcome_type: str
    horizon: int
    outcome_log_return: float
    outcome_simple_return: float
    outcome_start_utc: datetime
    outcome_end_utc: datetime
    outcome_available_at_utc: datetime
    alignment_mode: AlignmentMode


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise PanelAlignmentError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def aggregate_news_to_sessions(
    observations: tuple[NewsFeatureObservation, ...],
    *,
    market_group: str,
    calendar: StaticMarketCalendar,
) -> tuple[SessionNewsFeature, ...]:
    """Assign news by first usable availability, never by a later research timestamp."""

    grouped: dict[
        tuple[date, SessionLabel, str],
        list[NewsFeatureObservation],
    ] = {}
    for observation in observations:
        if observation.market_group != market_group:
            continue
        observed = _utc(observation.observed_at_utc, field="observed_at_utc")
        available = _utc(observation.available_at_utc, field="available_at_utc")
        if available < observed:
            raise PanelAlignmentError(
                f"{observation.source_timestamp}: feature available before it was observed"
            )
        if not math.isfinite(observation.value):
            raise PanelAlignmentError(
                f"{observation.source_timestamp}: feature value is not finite"
            )
        assignment = calendar.classify(available)
        if assignment.assigned_trading_date is None:
            continue
        key = (
            assignment.assigned_trading_date,
            assignment.label,
            observation.feature_name,
        )
        grouped.setdefault(key, []).append(observation)

    output: list[SessionNewsFeature] = []
    for (trading_date, session_label, feature_name), items in grouped.items():
        ordered = sorted(items, key=lambda item: item.available_at_utc.astimezone(UTC))
        values = [item.value for item in ordered]
        source_timestamps = tuple(sorted({item.source_timestamp for item in ordered}))
        output.append(
            SessionNewsFeature(
                market_group=market_group,
                trading_date=trading_date,
                session_label=session_label,
                feature_name=feature_name,
                observation_count=len(values),
                value_sum=sum(values),
                value_mean=sum(values) / len(values),
                first_available_at_utc=ordered[0].available_at_utc.astimezone(UTC),
                last_available_at_utc=ordered[-1].available_at_utc.astimezone(UTC),
                source_timestamps=source_timestamps,
            )
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.trading_date,
                item.session_label,
                item.feature_name,
            ),
        )
    )


def _outcome_interval(
    result: DailyReturn,
    bars_by_key: dict[tuple[str, date], DailyBar],
) -> tuple[datetime, datetime]:
    start_bar = bars_by_key.get((result.asset_id, result.start_trading_date))
    end_bar = bars_by_key.get((result.asset_id, result.end_trading_date))
    if start_bar is None or end_bar is None:
        raise PanelAlignmentError(
            f"missing bars for return {result.asset_id} "
            f"{result.start_trading_date}->{result.end_trading_date}"
        )
    if result.return_type == "INTRADAY":
        start = start_bar.session_open_utc
        end = start_bar.session_close_utc
    elif result.return_type == "OVERNIGHT":
        start = start_bar.session_close_utc
        end = end_bar.session_open_utc
    elif result.return_type == "CLOSE_TO_CLOSE":
        start = start_bar.session_close_utc
        end = end_bar.session_close_utc
    else:
        raise PanelAlignmentError(f"unsupported return_type: {result.return_type}")
    start_utc = _utc(start, field="outcome_start_utc")
    end_utc = _utc(end, field="outcome_end_utc")
    if start_utc >= end_utc:
        raise PanelAlignmentError("outcome interval is empty or reversed")
    return start_utc, end_utc


def align_session_features_to_returns(
    features: tuple[SessionNewsFeature, ...],
    returns: tuple[DailyReturn, ...],
    bars: tuple[DailyBar, ...],
    *,
    asset_market_groups: dict[str, str],
    alignment_mode: AlignmentMode = "PREDICTIVE",
    exposure_statistic: Literal["SUM", "MEAN"] = "SUM",
) -> tuple[AlignedPanelObservation, ...]:
    """Join session features to outcomes under an explicit temporal ordering rule.

    PREDICTIVE requires every contributing feature to be available no later than the
    outcome start. EVENT_WINDOW requires availability within the outcome interval and
    is therefore labeled contemporaneous rather than predictive.
    """

    if alignment_mode not in {"PREDICTIVE", "EVENT_WINDOW"}:
        raise PanelAlignmentError(f"unsupported alignment_mode: {alignment_mode}")
    if exposure_statistic not in {"SUM", "MEAN"}:
        raise PanelAlignmentError(
            f"unsupported exposure_statistic: {exposure_statistic}"
        )
    validated_bars = validate_daily_bars(bars)
    bars_by_key = {
        (bar.asset_id, bar.trading_date): bar
        for bar in validated_bars
    }
    features_by_key: dict[tuple[str, date], list[SessionNewsFeature]] = {}
    for feature in features:
        features_by_key.setdefault(
            (feature.market_group, feature.trading_date),
            [],
        ).append(feature)

    output: list[AlignedPanelObservation] = []
    for result in returns:
        market_group = asset_market_groups.get(result.asset_id)
        if market_group is None:
            raise PanelAlignmentError(
                f"asset has no market_group mapping: {result.asset_id}"
            )
        outcome_start, outcome_end = _outcome_interval(result, bars_by_key)
        for feature in features_by_key.get((market_group, result.trading_date), []):
            feature_time = _utc(
                feature.last_available_at_utc,
                field="feature.last_available_at_utc",
            )
            if alignment_mode == "PREDICTIVE":
                if feature_time > outcome_start:
                    continue
            else:
                if not (outcome_start < feature_time <= outcome_end):
                    continue
            exposure = (
                feature.value_sum
                if exposure_statistic == "SUM"
                else feature.value_mean
            )
            output.append(
                AlignedPanelObservation(
                    asset_id=result.asset_id,
                    market_group=market_group,
                    trading_date=result.trading_date,
                    session_label=feature.session_label,
                    feature_name=feature.feature_name,
                    exposure_value=exposure,
                    exposure_count=feature.observation_count,
                    exposure_available_at_utc=feature_time,
                    outcome_type=result.return_type,
                    horizon=result.horizon,
                    outcome_log_return=result.log_return,
                    outcome_simple_return=result.simple_return,
                    outcome_start_utc=outcome_start,
                    outcome_end_utc=outcome_end,
                    outcome_available_at_utc=_utc(
                        result.available_at_utc,
                        field="return.available_at_utc",
                    ),
                    alignment_mode=alignment_mode,
                )
            )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.asset_id,
                item.trading_date,
                item.outcome_type,
                item.horizon,
                item.session_label,
                item.feature_name,
            ),
        )
    )
