from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

SplitName = Literal["DESIGN", "TUNE", "VALIDATE", "FINAL"]


class TimeSplitError(ValueError):
    """Raised when research time partitions overlap, gap, or leak future dates."""


@dataclass(frozen=True, slots=True)
class StudyPeriod:
    name: SplitName
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise TimeSplitError(f"{self.name}: start_date must be <= end_date")

    def contains(self, value: date) -> bool:
        return self.start_date <= value <= self.end_date


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if self.train_start > self.train_end:
            raise TimeSplitError(f"{self.fold_id}: invalid training interval")
        if self.test_start > self.test_end:
            raise TimeSplitError(f"{self.fold_id}: invalid test interval")
        if self.train_end >= self.test_start:
            raise TimeSplitError(f"{self.fold_id}: training data reaches into test interval")


DEFAULT_STUDY_PERIODS: tuple[StudyPeriod, ...] = (
    StudyPeriod("DESIGN", date(2015, 2, 19), date(2019, 12, 31)),
    StudyPeriod("TUNE", date(2020, 1, 1), date(2022, 12, 31)),
    StudyPeriod("VALIDATE", date(2023, 1, 1), date(2024, 12, 31)),
    StudyPeriod("FINAL", date(2025, 1, 1), date(2026, 6, 30)),
)


def validate_study_periods(
    periods: tuple[StudyPeriod, ...],
    *,
    require_contiguous: bool = True,
) -> tuple[StudyPeriod, ...]:
    if not periods:
        raise TimeSplitError("study periods are empty")
    ordered = tuple(sorted(periods, key=lambda item: item.start_date))
    names = [item.name for item in ordered]
    if len(set(names)) != len(names):
        raise TimeSplitError("study period names must be unique")
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.end_date >= current.start_date:
            raise TimeSplitError(
                f"study periods overlap: {previous.name} and {current.name}"
            )
        if require_contiguous and previous.end_date + timedelta(days=1) != current.start_date:
            raise TimeSplitError(
                f"study periods have a gap: {previous.name} to {current.name}"
            )
    return ordered


def assign_study_period(
    value: date,
    periods: tuple[StudyPeriod, ...] = DEFAULT_STUDY_PERIODS,
) -> SplitName | None:
    for period in validate_study_periods(periods):
        if period.contains(value):
            return period.name
    return None


def expanding_walk_forward_folds(
    observation_dates: tuple[date, ...],
    *,
    first_test_date: date,
    test_window_days: int,
    step_days: int | None = None,
    minimum_training_days: int = 365,
) -> tuple[WalkForwardFold, ...]:
    """Create calendar-bounded expanding folds without random resampling.

    Empty calendar windows are skipped; each emitted fold is clipped to observed
    dates and training always ends strictly before the first observed test date.
    """

    if test_window_days <= 0:
        raise TimeSplitError("test_window_days must be positive")
    if minimum_training_days <= 0:
        raise TimeSplitError("minimum_training_days must be positive")
    step = test_window_days if step_days is None else step_days
    if step <= 0:
        raise TimeSplitError("step_days must be positive")
    dates = tuple(sorted(set(observation_dates)))
    if not dates:
        raise TimeSplitError("observation_dates are empty")
    folds: list[WalkForwardFold] = []
    cursor = first_test_date
    last_date = dates[-1]
    while cursor <= last_date:
        window_end = cursor + timedelta(days=test_window_days - 1)
        test_dates = tuple(item for item in dates if cursor <= item <= window_end)
        if test_dates:
            test_start = test_dates[0]
            test_end = test_dates[-1]
            train_dates = tuple(item for item in dates if item < test_start)
            if train_dates and (train_dates[-1] - train_dates[0]).days >= minimum_training_days:
                folds.append(
                    WalkForwardFold(
                        fold_id=f"WF{len(folds) + 1:03d}",
                        train_start=train_dates[0],
                        train_end=train_dates[-1],
                        test_start=test_start,
                        test_end=test_end,
                    )
                )
        cursor += timedelta(days=step)
    if not folds:
        raise TimeSplitError("no walk-forward fold met the training and test gates")
    return tuple(folds)
