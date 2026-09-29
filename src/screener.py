import pandas as pd
from .corporate_actions import effective_target
from .price_loader import price_at
from .report_loader import latest_reports


SCREEN_COLUMNS = ("market_date", "ticker", "name", "broker", "report_date", "report_age_days", "previous_target_price", "original_target_price", "effective_target_price", "raw_close", "target_upside", "holding_status", "average_cost", "holding_return", "screen_status", "report_event")


def screen(reports, actions, raw_close, market_date, threshold=.30, max_age_days=90):
    rows = []
    for _, report in latest_reports(reports, market_date).iterrows():
        age = (pd.Timestamp(market_date) - report.report_date).days
        raw = price_at(raw_close, market_date, report.ticker)
        effective = effective_target(report, market_date, actions)
        upside = round(effective / raw - 1, 12)
        cost = report.average_cost
        rows.append(dict(market_date=pd.Timestamp(market_date).date().isoformat(), ticker=report.ticker, name=report["name"], broker=report.broker, report_date=report.report_date.date().isoformat(), report_age_days=age, previous_target_price=report.previous_target_price, original_target_price=report.original_target_price, effective_target_price=effective, raw_close=raw, target_upside=upside, holding_status=report.holding_status, average_cost=cost, holding_return=(raw / cost - 1 if pd.notna(cost) and cost > 0 else None), screen_status="EXPIRED" if age > max_age_days else "CANDIDATE" if upside > threshold else "ACTIVE_BELOW_THRESHOLD", report_event=age == 0))
    return pd.DataFrame(rows, columns=SCREEN_COLUMNS)


CANDIDATE_COLUMNS = ("ticker", "name", "broker", "report_date", "effective_target_price", "raw_close", "target_upside", "report_age_days")


def candidate_view(current):
    """Compact current candidate pool for human review; no research state is changed."""
    candidates = current.loc[current["screen_status"] == "CANDIDATE", CANDIDATE_COLUMNS].copy()
    return candidates.sort_values(["target_upside", "ticker", "broker"], ascending=[False, True, True]).reset_index(drop=True)
