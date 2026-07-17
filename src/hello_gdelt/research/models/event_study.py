from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
from scipy import stats


class EventStudyError(ValueError):
    """Raised when an event-study sample violates timing or completeness gates."""


@dataclass(frozen=True, slots=True)
class EventAbnormalReturn:
    event_key: str
    asset_id: str
    event_date: date
    relative_day: int
    abnormal_return: float


@dataclass(frozen=True, slots=True)
class DailyAverageAbnormalReturn:
    relative_day: int
    event_count: int
    average_abnormal_return: float
    standard_error: float | None


@dataclass(frozen=True, slots=True)
class EventWindowResult:
    window_start: int
    window_end: int
    complete_event_count: int
    incomplete_event_count: int
    mean_cumulative_abnormal_return: float
    standard_error: float
    t_statistic: float
    p_value: float
    confidence_level: float
    confidence_lower: float
    confidence_upper: float
    bootstrap_iterations: int
    bootstrap_cluster: str = "ASSET"


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    daily_average_abnormal_returns: tuple[DailyAverageAbnormalReturn, ...]
    windows: tuple[EventWindowResult, ...]
    event_count: int
    asset_count: int
    minimum_event_spacing_days: int
    confidence_level: float


def _validate_events(
    observations: Sequence[EventAbnormalReturn],
    *,
    minimum_event_spacing_days: int,
) -> tuple[EventAbnormalReturn, ...]:
    materialized = tuple(observations)
    if not materialized:
        raise EventStudyError("event-study observations are empty")
    if minimum_event_spacing_days < 0:
        raise EventStudyError("minimum_event_spacing_days must be non-negative")
    seen: set[tuple[str, int]] = set()
    event_identity: dict[str, tuple[str, date]] = {}
    event_dates_by_asset: dict[str, set[date]] = {}
    for item in materialized:
        if not item.event_key or not item.asset_id:
            raise EventStudyError("event_key and asset_id are required")
        if not math.isfinite(item.abnormal_return):
            raise EventStudyError(
                f"non-finite abnormal return for {item.event_key} day {item.relative_day}"
            )
        key = (item.event_key, item.relative_day)
        if key in seen:
            raise EventStudyError(f"duplicate event-relative-day row: {key}")
        seen.add(key)
        identity = (item.asset_id, item.event_date)
        existing = event_identity.get(item.event_key)
        if existing is None:
            event_identity[item.event_key] = identity
            event_dates_by_asset.setdefault(item.asset_id, set()).add(item.event_date)
        elif existing != identity:
            raise EventStudyError(
                f"event_key {item.event_key} maps to multiple asset/date identities"
            )
    if minimum_event_spacing_days > 0:
        for asset_id, event_dates in event_dates_by_asset.items():
            ordered = sorted(event_dates)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                spacing = (current - previous).days
                if spacing < minimum_event_spacing_days:
                    raise EventStudyError(
                        f"overlapping events for {asset_id}: {previous} and {current} "
                        f"are only {spacing} days apart"
                    )
    return tuple(
        sorted(
            materialized,
            key=lambda item: (item.relative_day, item.event_key),
        )
    )


def _daily_averages(
    observations: tuple[EventAbnormalReturn, ...],
) -> tuple[DailyAverageAbnormalReturn, ...]:
    by_day: dict[int, list[float]] = {}
    for item in observations:
        by_day.setdefault(item.relative_day, []).append(item.abnormal_return)
    output: list[DailyAverageAbnormalReturn] = []
    for relative_day in sorted(by_day):
        values = np.asarray(by_day[relative_day], dtype=np.float64)
        standard_error = (
            None
            if values.size < 2
            else float(values.std(ddof=1) / math.sqrt(values.size))
        )
        output.append(
            DailyAverageAbnormalReturn(
                relative_day=relative_day,
                event_count=int(values.size),
                average_abnormal_return=float(values.mean()),
                standard_error=standard_error,
            )
        )
    return tuple(output)


def _event_cars(
    observations: tuple[EventAbnormalReturn, ...],
    *,
    window_start: int,
    window_end: int,
) -> tuple[dict[str, tuple[str, float]], int]:
    required_days = set(range(window_start, window_end + 1))
    by_event: dict[str, dict[int, EventAbnormalReturn]] = {}
    for item in observations:
        if window_start <= item.relative_day <= window_end:
            by_event.setdefault(item.event_key, {})[item.relative_day] = item
    all_events = {item.event_key for item in observations}
    complete: dict[str, tuple[str, float]] = {}
    for event_key, rows in by_event.items():
        if set(rows) == required_days:
            sample = next(iter(rows.values()))
            complete[event_key] = (
                sample.asset_id,
                float(sum(row.abnormal_return for row in rows.values())),
            )
    return complete, len(all_events) - len(complete)


def _asset_cluster_bootstrap(
    cars: dict[str, tuple[str, float]],
    *,
    iterations: int,
    confidence_level: float,
    seed: int,
) -> tuple[float, float]:
    by_asset: dict[str, list[float]] = {}
    for asset_id, car in cars.values():
        by_asset.setdefault(asset_id, []).append(car)
    assets = tuple(sorted(by_asset))
    if len(assets) < 2:
        raise EventStudyError("asset-cluster bootstrap requires at least two assets")
    rng = np.random.default_rng(seed)
    bootstrap_means = np.empty(iterations, dtype=np.float64)
    for iteration in range(iterations):
        sampled_assets = rng.choice(assets, size=len(assets), replace=True)
        sampled_values: list[float] = []
        for asset_id in sampled_assets:
            sampled_values.extend(by_asset[str(asset_id)])
        bootstrap_means[iteration] = float(np.mean(sampled_values))
    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(
        bootstrap_means,
        [alpha / 2.0, 1.0 - alpha / 2.0],
        method="linear",
    )
    return float(lower), float(upper)


def run_event_study(
    observations: Sequence[EventAbnormalReturn],
    *,
    windows: Sequence[tuple[int, int]] = ((-5, -1), (0, 0), (0, 1), (0, 5), (0, 20)),
    confidence_level: float = 0.95,
    bootstrap_iterations: int = 2_000,
    bootstrap_seed: int = 20260717,
    minimum_event_spacing_days: int = 21,
) -> EventStudyResult:
    """Summarize abnormal returns with complete-window and overlap controls.

    Inference is performed on event-level CARs. Confidence intervals use an
    asset-cluster bootstrap so multiple events for one asset remain dependent.
    """

    if not 0 < confidence_level < 1:
        raise EventStudyError("confidence_level must lie strictly between 0 and 1")
    if bootstrap_iterations < 200:
        raise EventStudyError("bootstrap_iterations must be at least 200")
    normalized_windows = tuple(windows)
    if not normalized_windows:
        raise EventStudyError("at least one event window is required")
    if len(set(normalized_windows)) != len(normalized_windows):
        raise EventStudyError("event windows must be unique")
    for start, end in normalized_windows:
        if start > end:
            raise EventStudyError(f"invalid event window [{start}, {end}]")

    validated = _validate_events(
        observations,
        minimum_event_spacing_days=minimum_event_spacing_days,
    )
    event_keys = {item.event_key for item in validated}
    assets = {item.asset_id for item in validated}
    window_results: list[EventWindowResult] = []
    for window_index, (window_start, window_end) in enumerate(normalized_windows):
        cars, incomplete_count = _event_cars(
            validated,
            window_start=window_start,
            window_end=window_end,
        )
        if len(cars) < 2:
            raise EventStudyError(
                f"window [{window_start}, {window_end}] has fewer than two complete events"
            )
        values = np.asarray([car for _, car in cars.values()], dtype=np.float64)
        mean_car = float(values.mean())
        standard_error = float(values.std(ddof=1) / math.sqrt(values.size))
        if standard_error == 0:
            t_statistic = (
                math.copysign(float("inf"), mean_car)
                if mean_car != 0
                else 0.0
            )
            p_value = 0.0 if mean_car != 0 else 1.0
        else:
            t_statistic = mean_car / standard_error
            p_value = float(
                2.0 * stats.t.sf(abs(t_statistic), df=values.size - 1)
            )
        confidence_lower, confidence_upper = _asset_cluster_bootstrap(
            cars,
            iterations=bootstrap_iterations,
            confidence_level=confidence_level,
            seed=bootstrap_seed + window_index,
        )
        window_results.append(
            EventWindowResult(
                window_start=window_start,
                window_end=window_end,
                complete_event_count=int(values.size),
                incomplete_event_count=incomplete_count,
                mean_cumulative_abnormal_return=mean_car,
                standard_error=standard_error,
                t_statistic=t_statistic,
                p_value=p_value,
                confidence_level=confidence_level,
                confidence_lower=confidence_lower,
                confidence_upper=confidence_upper,
                bootstrap_iterations=bootstrap_iterations,
            )
        )
    return EventStudyResult(
        daily_average_abnormal_returns=_daily_averages(validated),
        windows=tuple(window_results),
        event_count=len(event_keys),
        asset_count=len(assets),
        minimum_event_spacing_days=minimum_event_spacing_days,
        confidence_level=confidence_level,
    )
