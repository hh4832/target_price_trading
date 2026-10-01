import pandas as pd
from .config import HORIZONS
from .price_loader import price_at


RETURN_COLUMNS = ("signal_id", "signal_date", "ticker", "entry_date", "entry_adj_open", "benchmark_entry_adj_open") + tuple(f"{field}_O1_C{h}" for h in HORIZONS for field in ("stock_return", "benchmark_return", "excess_return", "status"))


def calculate_returns(ledger, raw_close, raw_open, adj_close, benchmark="0050"):
    dates = pd.DatetimeIndex(pd.to_datetime(raw_close.index)).normalize().sort_values()
    dataset_latest = {
        "raw_close": pd.DatetimeIndex(pd.to_datetime(raw_close.index)).normalize().max().date(),
        "raw_open": pd.DatetimeIndex(pd.to_datetime(raw_open.index)).normalize().max().date(),
        "adj_close": pd.DatetimeIndex(pd.to_datetime(adj_close.index)).normalize().max().date(),
    }
    print(
        "PRICE_DATASET_DIAGNOSTIC "
        + " ".join(f"{name}_latest={date}" for name, date in dataset_latest.items())
    )
    rows = []
    for signal in ledger.itertuples(index=False):
        t = pd.Timestamp(signal.signal_date)
        if t not in dates:
            raise ValueError(f"Signal date missing from market calendar: {t}")
        loc = dates.get_loc(t)
        result = dict(signal_id=signal.signal_id, signal_date=signal.signal_date, ticker=signal.ticker, entry_date=None, entry_adj_open=None, benchmark_entry_adj_open=None)
        if loc + 1 >= len(dates):
            for h in HORIZONS:
                result[f"status_O1_C{h}"] = "PENDING"
            rows.append(result)
            continue
        entry_date = dates[loc + 1]
        result["entry_date"] = entry_date.date().isoformat()
        entries = {}
        for ticker in (signal.ticker, benchmark):
            try:
                open_ = price_at(raw_open, entry_date, ticker)
                close_ = price_at(raw_close, entry_date, ticker)
                adjustment = price_at(adj_close, entry_date, ticker) / close_
            except ValueError as exc:
                print(
                    "PRICE_ENTRY_DIAGNOSTIC "
                    f"signal_id={signal.signal_id} signal_date={signal.signal_date} "
                    f"entry_date={entry_date.date()} ticker={ticker} "
                    f"ticker_repr={ticker!r} ticker_type={type(ticker).__name__} "
                    f"string_ticker_present_raw_open={str(ticker) in raw_open.columns} "
                    f"exact_ticker_present_raw_open={ticker in raw_open.columns} "
                    f"raw_close_latest={dataset_latest['raw_close']} "
                    f"raw_open_latest={dataset_latest['raw_open']} "
                    f"adj_close_latest={dataset_latest['adj_close']} "
                    f"error={exc}"
                )
                raise
            entries[ticker] = open_ * adjustment
        result["entry_adj_open"] = entries[signal.ticker]
        result["benchmark_entry_adj_open"] = entries[benchmark]
        for h in HORIZONS:
            if loc + h >= len(dates):
                result[f"status_O1_C{h}"] = "PENDING"
                continue
            end = dates[loc + h]
            stock = price_at(adj_close, end, signal.ticker) / entries[signal.ticker] - 1
            bench = price_at(adj_close, end, benchmark) / entries[benchmark] - 1
            result.update({f"stock_return_O1_C{h}": stock, f"benchmark_return_O1_C{h}": bench, f"excess_return_O1_C{h}": stock - bench, f"status_O1_C{h}": "MATURE"})
        rows.append(result)
    return pd.DataFrame(rows, columns=RETURN_COLUMNS)
