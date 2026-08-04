from core.bess.tie_detection import Window, detect_tie_windows


def _prices(n: int) -> tuple[list[float], list[float]]:
    return [1.0] * n, [0.5] * n


def test_no_ties_returns_empty_list():
    buy, sell = _prices(10)
    margins = [10.0] * 10  # every period has a large, clear margin
    assert detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05) == []


def test_isolated_tie_produces_single_padded_window():
    buy, sell = _prices(10)
    margins = [10.0] * 10
    margins[5] = 0.0001  # near-zero margin at period 5
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert windows == [
        Window(start=3, end=8)
    ]  # 5-2 .. 5+2+1, clamped to bounds by construction here


def test_two_ties_close_together_merge_into_one_window():
    buy, sell = _prices(10)
    margins = [10.0] * 10
    margins[4] = 0.0001
    margins[5] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert len(windows) == 1
    assert windows[0].start <= 2 and windows[0].end >= 8


def test_two_ties_far_apart_stay_separate():
    buy, sell = _prices(20)
    margins = [10.0] * 20
    margins[2] = 0.0001
    margins[17] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    assert len(windows) == 2


def test_windows_clamped_to_horizon_bounds():
    buy, sell = _prices(5)
    margins = [10.0] * 5
    margins[0] = 0.0001
    margins[4] = 0.0001
    windows = detect_tie_windows(margins, buy, sell, soe_step_kwh=0.05, pad=2)
    for w in windows:
        assert 0 <= w.start < w.end <= 5
