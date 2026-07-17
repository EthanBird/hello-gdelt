from hello_gdelt.hypothesis.statistics import bh_fdr


def test_bh_fdr_is_monotone_in_rank() -> None:
    adjusted = bh_fdr([0.01, 0.04, 0.03, 0.002])
    assert all(0 <= value <= 1 for value in adjusted)
    assert adjusted[3] <= adjusted[0] <= adjusted[2]
