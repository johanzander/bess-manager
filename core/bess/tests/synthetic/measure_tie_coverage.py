"""Measurement harness for the #450 tie-detection coverage validation
suite (see docs/superpowers/specs/2026-08-05-tie-detection-synthetic-
validation-design.md)."""

_BUCKET_ORDER = ["<0.1x", "0.1x-0.5x", "0.5x-1.0x", "1.0x-2.0x", ">2.0x"]


def _bucket_for_ratio(ratio: float) -> str:
    if ratio < 0.1:
        return "<0.1x"
    if ratio < 0.5:
        return "0.1x-0.5x"
    if ratio < 1.0:
        return "0.5x-1.0x"
    if ratio < 2.0:
        return "1.0x-2.0x"
    return ">2.0x"


def classify_margin_ratios(
    tie_margins: list[float], value_slopes: list[float], soe_step_kwh: float
) -> dict[str, int]:
    counts = dict.fromkeys(_BUCKET_ORDER, 0)
    for margin, slope in zip(tie_margins, value_slopes, strict=True):
        worst_case_noise = soe_step_kwh * abs(slope)
        ratio = margin / worst_case_noise if worst_case_noise > 0 else float("inf")
        counts[_bucket_for_ratio(ratio)] += 1
    return counts
