import hashlib
import pandas as pd


LEDGER_COLUMNS = ("signal_id", "signal_date", "ticker", "name", "broker", "report_date", "report_age_days", "original_target_price", "effective_target_price", "signal_raw_close", "signal_target_upside", "signal_type", "git_commit", "created_at")


def generate_signals(current, previous, ledger, commit, created_at, threshold=.30):
    previous = previous.set_index(["ticker", "broker"]) if not previous.empty else None
    seen = set(ledger.signal_id) if not ledger.empty else set()
    rows = []
    for row in current.itertuples(index=False):
        if row.screen_status != "CANDIDATE":
            continue
        key = (row.ticker, row.broker)
        if previous is None or key not in previous.index:
            # No previous observable close: cannot prove a threshold crossing.
            continue
        prior = previous.loc[key]
        if float(prior.target_upside) > threshold:
            continue
        signal_id = hashlib.sha256(f"{row.market_date}|{row.ticker}|{row.broker}|THRESHOLD_CROSSING".encode()).hexdigest()[:24]
        if signal_id in seen:
            continue
        rows.append(dict(signal_id=signal_id, signal_date=row.market_date, ticker=row.ticker, name=row.name, broker=row.broker, report_date=row.report_date, report_age_days=row.report_age_days, original_target_price=row.original_target_price, effective_target_price=row.effective_target_price, signal_raw_close=row.raw_close, signal_target_upside=row.target_upside, signal_type="THRESHOLD_CROSSING", git_commit=commit, created_at=created_at))
    if not rows:
        return ledger.copy()
    if ledger.empty:
        return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    return pd.concat([ledger, pd.DataFrame(rows, columns=LEDGER_COLUMNS)], ignore_index=True)
