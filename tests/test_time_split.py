from datetime import date, timedelta

import pytest

from hello_gdelt.research.time_split import (
    DEFAULT_STUDY_PERIODS,
    StudyPeriod,
    TimeSplitError,
    assign_study_period,
    expanding_walk_forward_folds,
    validate_study_periods,
)


def test_frozen_study_period_boundaries() -> None:
    assert validate_study_periods(DEFAULT_STUDY_PERIODS) == DEFAULT_STUDY_PERIODS
    assert assign_study_period(date(2015, 2, 19)) == "DESIGN"
    assert assign_study_period(date(2019, 12, 31)) == "DESIGN"
    assert assign_study_period(date(2020, 1, 1)) == "TUNE"
    assert assign_study_period(date(2024, 12, 31)) == "VALIDATE"
    assert assign_study_period(date(2025, 1, 1)) == "FINAL"
    assert assign_study_period(date(2026, 6, 30)) == "FINAL"
    assert assign_study_period(date(2026, 7, 1)) is None


def test_study_period_overlap_and_gap_are_rejected() -> None:
    with pytest.raises(TimeSplitError, match="overlap"):
        validate_study_periods(
            (
                StudyPeriod("DESIGN", date(2020, 1, 1), date(2020, 12, 31)),
                StudyPeriod("TUNE", date(2020, 12, 31), date(2021, 12, 31)),
            )
        )
    with pytest.raises(TimeSplitError, match="gap"):
        validate_study_periods(
            (
                StudyPeriod("DESIGN", date(2020, 1, 1), date(2020, 12, 31)),
                StudyPeriod("TUNE", date(2021, 1, 2), date(2021, 12, 31)),
            )
        )


def test_expanding_walk_forward_never_reaches_into_test_window() -> None:
    start = date(2019, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(900))
    folds = expanding_walk_forward_folds(
        dates,
        first_test_date=date(2020, 7, 1),
        test_window_days=90,
        minimum_training_days=365,
    )
    assert len(folds) >= 3
    assert all(item.train_end < item.test_start for item in folds)
    assert all(item.train_start == start for item in folds)
    assert [item.fold_id for item in folds] == [
        f"WF{index:03d}" for index in range(1, len(folds) + 1)
    ]


def test_walk_forward_rejects_insufficient_history() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(30))
    with pytest.raises(TimeSplitError, match="no walk-forward fold"):
        expanding_walk_forward_folds(
            dates,
            first_test_date=date(2026, 1, 15),
            test_window_days=7,
            minimum_training_days=365,
        )
