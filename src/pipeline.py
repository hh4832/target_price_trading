import argparse
import json
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Config
from .corporate_actions import parse_actions
from .output import archive, clients, put_file, read_csv, read_state, sheet_values, verify_folder
from .price_loader import load_finlab_prices, market_dates, price_at
from .report_loader import parse_reports
from .research_summary import summarize
from .returns import calculate_returns
from .screener import SCREEN_COLUMNS, screen
from .signal_ledger import LEDGER_COLUMNS, generate_signals


def check_action_coverage(reports, actions, raw_close, adj_close, market_date):
    # Large total-return adjustment discontinuities require an explicit event classification.
    # Smaller actions still require manual review; this heuristic is not a complete action feed.
    dates = market_dates(raw_close)
    for ticker in reports.ticker.unique():
        if ticker not in raw_close or ticker not in adj_close:
            raise ValueError(f"Missing price series {ticker}")
        starts = reports.loc[reports.ticker == ticker, "report_date"]
        selected = dates[(dates >= starts.min()) & (dates <= market_date)]
        if len(selected) < 2:
            continue
        ratio = (adj_close.loc[selected, ticker] / raw_close.loc[selected, ticker]).dropna()
        jumps = ratio.div(ratio.shift()).dropna()
        for date in jumps.index[abs(jumps - 1) > .10]:
            if actions.loc[(actions.ticker == ticker) & (actions.effective_date == date)].empty:
                raise ValueError(f"Unclassified corporate action candidate {ticker} {date.date()}; add reviewed CorporateActions row")


def run():
    cfg = Config()
    drive, sheets = clients()
    verify_folder(drive, cfg.folder_id)
    reports = parse_reports(sheet_values(sheets, cfg.sheet_id, "基本面選股"))
    try:
        actions = parse_actions(sheet_values(sheets, cfg.sheet_id, "CorporateActions"))
    except Exception as exc:
        # A missing optional tab is allowed; malformed existing tabs are not.
        if "Unable to parse range" not in str(exc):
            raise
        actions = parse_actions([])
    raw_close, raw_open, adj_close = load_finlab_prices()
    dates = market_dates(raw_close)
    market_date = dates[-1]
    state = read_state(drive, cfg.folder_id)
    if state.get("last_successful_market_date") and market_date <= pd.Timestamp(state["last_successful_market_date"]):
        print(f"DATA_NOT_UPDATED: latest_available_market_date={market_date.date()}; last_successful_market_date={state['last_successful_market_date']}")
        return "DATA_NOT_UPDATED"
    check_action_coverage(reports, actions, raw_close, adj_close, market_date)
    current = screen(reports, actions, raw_close, market_date, cfg.threshold, cfg.max_age_days)
    previous = read_csv(drive, cfg.folder_id, "last_screen.csv", SCREEN_COLUMNS)
    ledger = read_csv(drive, cfg.folder_id, "signal_ledger.csv", LEDGER_COLUMNS)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() or os.environ.get("GITHUB_REF_NAME", "detached")
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    ledger = generate_signals(current, previous, ledger, commit, now, cfg.threshold)
    returns = calculate_returns(ledger, raw_close, raw_open, adj_close)
    summary = summarize(returns)
    info = "\n".join([f"execution_timestamp={now}", "timezone=Asia/Taipei", f"git_commit={commit}", f"branch={branch}", f"latest_finlab_market_date={market_date.date()}", f"processed_market_date={market_date.date()}", f"TARGET_UPSIDE_THRESHOLD={cfg.threshold}", f"REPORT_MAX_AGE_DAYS={cfg.max_age_days}", "price_source=FinLab raw price:收盤價; raw price:開盤價; adjusted etl:adj_close", "benchmark=0050", "data_validation=PASS; corporate action coverage heuristic >10% ratio jump plus manually classified events", "research_conclusion=修改後再測", ""])
    frames = {"daily_screen.csv": current, "signal_ledger.csv": ledger, "signal_returns.csv": returns, "research_summary.csv": summary, "last_screen.csv": current, "report_snapshot.csv": reports, "corporate_actions_snapshot.csv": actions}
    name = archive(drive, cfg.folder_id, frames, info, commit)
    put_file(drive, cfg.folder_id, "state.json", json.dumps({"last_successful_market_date": str(market_date.date()), "last_archive": name}).encode(), "application/json", replace=True)
    print(f"SUCCESS: {name} market_date={market_date.date()} signals={len(ledger)}")
    return name


if __name__ == "__main__":
    run()
