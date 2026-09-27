import pandas as pd


HEADERS = {"Ticker": "ticker", "名稱": "name", "報告日期": "report_date", "前次目標價": "previous_target_price", "本次目標價": "original_target_price", "投顧": "broker", "持有": "holding_status", "買進日期": "buy_date", "成本均價": "average_cost"}


def parse_reports(values):
    if not values:
        raise ValueError("Report sheet is empty")
    headers = [str(v).strip() for v in values[0]]
    required = {"Ticker", "名稱", "報告日期", "本次目標價", "投顧"}
    if not required.issubset(headers) or len(headers) != len(set(headers)):
        raise ValueError(f"Missing or duplicate report columns: {required - set(headers)}")
    records = [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:] if any(str(x).strip() for x in row)]
    df = pd.DataFrame(records).rename(columns=HEADERS)
    if df.empty:
        raise ValueError("No report observations")
    for col in HEADERS.values():
        if col not in df:
            df[col] = ""
    df["ticker"] = df.ticker.astype(str).str.strip()
    df["broker"] = df.broker.astype(str).str.strip()
    df["report_date"] = pd.to_datetime(df.report_date, errors="raise").dt.normalize()
    for col in ("original_target_price", "previous_target_price", "average_cost"):
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")
    if (df.original_target_price <= 0).any() or df.original_target_price.isna().any() or (df.ticker == "").any() or (df.broker == "").any():
        raise ValueError("Invalid report ticker, broker or target price")
    # Two distinct reports on the same date for the same broker need an explicit time or ID.
    if df.duplicated(["ticker", "broker", "report_date"]).any():
        raise ValueError("Ambiguous duplicate ticker/broker/report_date")
    return df


def latest_reports(reports, date):
    eligible = reports.loc[reports.report_date <= pd.Timestamp(date)]
    return eligible.sort_values("report_date").drop_duplicates(["ticker", "broker"], keep="last").copy()
