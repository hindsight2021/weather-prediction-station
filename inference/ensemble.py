from __future__ import annotations


def ratio_vs_none(class_probability: float, none_probability: float) -> float:
    denominator = max(none_probability, 1e-6)
    return class_probability / denominator


def blend_ratios(monte_carlo_ratio: float, knn_ratio: float, monte_carlo_weight: float = 0.5) -> float:
    monte_carlo_weight = max(0.0, min(1.0, monte_carlo_weight))
    return monte_carlo_ratio * monte_carlo_weight + knn_ratio * (1.0 - monte_carlo_weight)


def tier_from_ratio(ratio: float, watch_threshold: float, advisory_threshold: float, warning_threshold: float) -> str:
    if ratio >= warning_threshold:
        return "warning"
    if ratio >= advisory_threshold:
        return "advisory"
    if ratio >= watch_threshold:
        return "watch"
    return "normal"
