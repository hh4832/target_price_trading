import hashlib
import pandas as pd


LEDGER_COLUMNS = ("signal_id", "signal_date", "ticker", "name", "broker", "report_date", "report_age_days", "original_target_price", "effective_target_price", "signal_raw_close", "signal_target_upside", "signal_type", "git_commit", "created_at")


def _report_key(row):
    return (str(row.ticker).strip(), str(row.broker).strip(), pd.Timestamp(row.report_date).date().isoformat())


def _append_signal(rows, seen, row, signal_type, commit, created_at):
    if signal_type == "NEW_REPORT_CANDIDATE":
        identity = f"{row.ticker}|{row.broker}|{pd.Timestamp(row.report_date).date().isoformat()}|{signal_type}"
    else:
        identity = f"{row.market_date}|{row.ticker}|{row.broker}|{signal_type}"
    signal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    if signal_id in seen:
        return
    rows.append(dict(signal_id=signal_id, signal_date=row.market_date, ticker=row.ticker, name=row.name, broker=row.broker, report_date=row.report_date, report_age_days=row.report_age_days, original_target_price=row.original_target_price, effective_target_price=row.effective_target_price, signal_raw_close=row.raw_close, signal_target_upside=row.target_upside, signal_type=signal_type, git_commit=commit, created_at=created_at))
    seen.add(signal_id)


def generate_signals(current, previous, ledger, commit, created_at, threshold=.30, new_report_keys=None):
    previous_indexed = previous.set_index(["ticker", "broker"]) if not previous.empty else None
    seen = set(ledger.signal_id.astype(str)) if not ledger.empty else set()
    new_report_keys = set(new_report_keys or ())
    rows = []
    for row in current.itertuples(index=False):
        if row.screen_status != "CANDIDATE":
            continue

        report_key = _report_key(row)
        # A report that first becomes observable while already above the threshold
        # is a distinct information event. report_event also provides a one-time
        # migration path for current-market-date reports created before the registry
        # taxonomy was introduced; the stable report-key signal ID keeps reruns idempotent.
        if report_key in new_report_keys or bool(row.report_event):
            _append_signal(rows, seen, row, "NEW_REPORT_CANDIDATE", commit, created_at)
            continue

        key = (row.ticker, row.broker)
        if previous_indexed is None or key not in previous_indexed.index:
            continue
        prior = previous_indexed.loc[key]
        if isinstance(prior, pd.DataFrame):
            raise ValueError(f"Ambiguous previous screen key {key}")
        if float(prior.target_upside) > threshold:
            continue
        _append_signal(rows, seen, row, "THRESHOLD_CROSSING", commit, created_at)

    if not rows:
        return ledger.copy()
    additions = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    if ledger.empty:
        return additions
    return pd.concat([ledger, additions], ignore_index=True)
