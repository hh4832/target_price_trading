import pandas as pd
from .config import HORIZONS


def summarize(returns, minimum_sample=30):
    rows = []
    for h in HORIZONS:
        s = f"stock_return_O1_C{h}"
        e = f"excess_return_O1_C{h}"
        subset = returns.loc[returns[f"status_O1_C{h}"] == "MATURE"] if not returns.empty else returns
        n = len(subset)
        rows.append(dict(horizon=f"O1_C{h}", sample_size=n, mean_return=subset[s].mean() if n else None, median_return=subset[s].median() if n else None, win_rate=(subset[s] > 0).mean() if n else None, mean_excess_return=subset[e].mean() if n else None, median_excess_return=subset[e].median() if n else None, positive_excess_return_rate=(subset[e] > 0).mean() if n else None, sample_status="INSUFFICIENT" if n < minimum_sample else "DESCRIPTIVE_ONLY"))
    return pd.DataFrame(rows)
