import pandas as pd


def load_finlab_prices():
    # Headless CI uses FINLAB_REFRESH_TOKEN, FINLAB_SESSION_ID, FINLAB_API_KEY.
    # Colab can use browser login or the same environment variables.
    from finlab import data
    raw_close = data.get("price:收盤價")
    raw_open = data.get("price:開盤價")
    adj_close = data.get("etl:adj_close")
    for label, frame in (("raw_close", raw_close), ("raw_open", raw_open), ("adj_close", adj_close)):
        if frame is None or frame.empty or frame.index.has_duplicates:
            raise ValueError(f"Invalid FinLab {label} data")
    return raw_close, raw_open, adj_close


def market_dates(raw_close):
    valid = raw_close.notna().any(axis=1)
    if not valid.any():
        raise ValueError("No available FinLab market prices")
    return pd.DatetimeIndex(pd.to_datetime(raw_close.index[valid])).normalize().sort_values()


def price_at(frame, date, ticker):
    date = pd.Timestamp(date)
    if ticker not in frame.columns or date not in frame.index:
        raise ValueError(f"Missing price {ticker} on {date.date()}")
    value = frame.at[date, ticker]
    if pd.isna(value) or float(value) <= 0:
        raise ValueError(f"Invalid price {ticker} on {date.date()}")
    return float(value)
