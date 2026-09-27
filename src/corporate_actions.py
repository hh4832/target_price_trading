import pandas as pd


ACTION_COLUMNS = ("ticker", "effective_date", "action_type", "target_factor")
SCALE_ACTIONS = {"SPLIT", "REVERSE_SPLIT", "CAPITAL_REDUCTION", "PAR_VALUE_CHANGE", "OTHER_SCALE"}


def parse_actions(values):
    if not values or len(values) == 1:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    headers = [str(x).strip() for x in values[0]]
    if not set(ACTION_COLUMNS).issubset(headers):
        raise ValueError("CorporateActions tab requires ticker,effective_date,action_type,target_factor")
    rows = [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:] if any(str(x).strip() for x in row)]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    df["effective_date"] = pd.to_datetime(df.effective_date, errors="raise").dt.normalize()
    df["target_factor"] = pd.to_numeric(df.target_factor, errors="raise")
    if (~df.action_type.isin(SCALE_ACTIONS | {"CASH_DIVIDEND"})).any() or (df.target_factor <= 0).any():
        raise ValueError("Unrecognized corporate action or invalid factor")
    if (df.loc[df.action_type == "CASH_DIVIDEND", "target_factor"] != 1).any():
        raise ValueError("Cash dividends cannot change target scale")
    if df.duplicated(["ticker", "effective_date", "action_type"]).any():
        raise ValueError("Duplicate corporate action")
    return df


def effective_target(report, market_date, actions):
    eligible = actions.loc[(actions.ticker == report.ticker) & (actions.effective_date > report.report_date) & (actions.effective_date <= pd.Timestamp(market_date))]
    return float(report.original_target_price) * float(eligible.target_factor.prod())
