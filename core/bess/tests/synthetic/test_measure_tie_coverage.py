from core.bess.tests.synthetic.measure_tie_coverage import classify_margin_ratios


def test_classifies_into_expected_buckets():
    # worst_case_noise = soe_step_kwh * abs(value_slope); ratio = margin / worst_case_noise
    # soe_step_kwh=0.1, value_slope=1.0 -> worst_case_noise=0.1 for every period below
    tie_margins = [0.005, 0.03, 0.08, 0.15, 0.25]
    value_slopes = [1.0, 1.0, 1.0, 1.0, 1.0]
    result = classify_margin_ratios(tie_margins, value_slopes, soe_step_kwh=0.1)
    # ratios: 0.05, 0.3, 0.8, 1.5, 2.5
    assert result == {
        "<0.1x": 1,
        "0.1x-0.5x": 1,
        "0.5x-1.0x": 1,
        "1.0x-2.0x": 1,
        ">2.0x": 1,
    }


def test_zero_value_slope_counts_as_over_2x():
    # worst_case_noise == 0 when value_slope == 0 -- ratio is undefined/infinite,
    # meaning grid-snapping cannot affect this period's ranking at all. Bucket
    # it in the "clearly not a tie" bucket rather than raising or dividing by zero.
    result = classify_margin_ratios([0.01], [0.0], soe_step_kwh=0.1)
    assert result == {
        "<0.1x": 0,
        "0.1x-0.5x": 0,
        "0.5x-1.0x": 0,
        "1.0x-2.0x": 0,
        ">2.0x": 1,
    }


def test_empty_input_returns_zero_counts():
    result = classify_margin_ratios([], [], soe_step_kwh=0.1)
    assert result == {
        "<0.1x": 0,
        "0.1x-0.5x": 0,
        "0.5x-1.0x": 0,
        "1.0x-2.0x": 0,
        ">2.0x": 0,
    }
