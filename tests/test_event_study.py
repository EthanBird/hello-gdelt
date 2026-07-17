from datetime import date, timedelta

import numpy as np
import pytest

pytest.importorskip("scipy")

from hello_gdelt.research.models.event_study import (
    EventAbnormalReturn,
    EventStudyError,
    run_event_study,
)


def synthetic_events(*, omit_last_day_for_final_event: bool = False):
    rng = np.random.default_rng(20260719)
    observations: list[EventAbnormalReturn] = []
    base_date = date(2024, 1, 15)
    for event_index in range(16):
        event_key = f"E{event_index:03d}"
        asset_id = f"A{event_index:03d}"
        event_date = base_date + timedelta(days=event_index * 30)
        for relative_day in range(-5, 6):
            if (
                omit_last_day_for_final_event
                and event_index == 15
                and relative_day == 5
            ):
                continue
            effect = 0.02 if relative_day == 0 else 0.0
            observations.append(
                EventAbnormalReturn(
                    event_key=event_key,
                    asset_id=asset_id,
                    event_date=event_date,
                    relative_day=relative_day,
                    abnormal_return=effect + rng.normal(scale=0.003),
                )
            )
    return observations


def test_event_study_recovers_event_day_effect_and_pretrend_null() -> None:
    result = run_event_study(
        synthetic_events(),
        windows=((-5, -1), (0, 0), (0, 1), (0, 5)),
        bootstrap_iterations=500,
    )
    by_window = {
        (item.window_start, item.window_end): item
        for item in result.windows
    }
    event_day = by_window[(0, 0)]
    pretrend = by_window[(-5, -1)]
    assert event_day.mean_cumulative_abnormal_return == pytest.approx(0.02, abs=0.003)
    assert event_day.p_value < 0.01
    assert event_day.confidence_lower > 0
    assert pretrend.mean_cumulative_abnormal_return == pytest.approx(0.0, abs=0.006)
    assert result.event_count == 16
    assert result.asset_count == 16


def test_event_study_reports_incomplete_windows_without_imputation() -> None:
    result = run_event_study(
        synthetic_events(omit_last_day_for_final_event=True),
        windows=((0, 5),),
        bootstrap_iterations=300,
    )
    window = result.windows[0]
    assert window.complete_event_count == 15
    assert window.incomplete_event_count == 1


def test_event_study_rejects_overlapping_same_asset_events() -> None:
    observations = synthetic_events()[:22]
    first_event_date = observations[0].event_date
    remapped = [
        EventAbnormalReturn(
            event_key=("SECOND" if item.event_key == "E001" else item.event_key),
            asset_id="SAME_ASSET",
            event_date=(
                first_event_date + timedelta(days=10)
                if item.event_key == "E001"
                else first_event_date
            ),
            relative_day=item.relative_day,
            abnormal_return=item.abnormal_return,
        )
        for item in observations
    ]
    with pytest.raises(EventStudyError, match="overlapping events"):
        run_event_study(
            remapped,
            windows=((0, 0),),
            bootstrap_iterations=200,
            minimum_event_spacing_days=21,
        )


def test_event_study_rejects_duplicate_event_day() -> None:
    observations = synthetic_events()
    observations.append(observations[0])
    with pytest.raises(EventStudyError, match="duplicate"):
        run_event_study(
            observations,
            windows=((0, 0),),
            bootstrap_iterations=200,
        )
