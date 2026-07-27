from typing import List, Tuple, Optional


def score_by_bins(value: Optional[float], bins: List[Tuple], default: int = 0) -> int:
    if value is None:
        return default
    for lower, upper, score in bins:
        if lower <= value < upper:
            return score
    return default
