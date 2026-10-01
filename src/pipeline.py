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
from .observability import PipelineProgress
from .price_loader import load_finlab_prices, market_dates, price_at
from .report_loader import parse_reports
from .report_registry import REGISTRY_COLUMNS, find_new_report_keys, update_report_registry
from .research_summary import summarize
from .returns import calculate_returns
from .screener import SCREEN_COLUMNS, candidate_view, screen
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


def validate_previous_state(state, previous):
    state_date = state.get("last_successful_market_date")
    if not state_date:
        if not previous.empty:
            raise ValueError("State integrity error: last_screen.csv exists but state.json has no last_successful_market_date")
        return None
    if previous.empty:
        raise ValueError("State integrity error: state.json has last_successful_market_date but last_screen.csv is empty")
    dates = pd.to_datetime(previous["market_date"], errors="coerce").dropna().dt.normalize().unique()
    if len(dates) != 1:
        raise ValueError(f"State integrity error: last_screen.csv must contain exactly one market_date; found {len(dates)}")
    previous_date = pd.Timestamp(dates[0]).date()
    expected_date = pd.Timestamp(state_date).date()
    if previous_date != expected_date:
        raise ValueError(
            f"State integrity error: state last_successful_market_date={expected_date} "
            f"but last_screen market_date={previous_date}"
        )
    return previous_date


def run():
    cfg = Config()
    progress = PipelineProgress(total=20, label="TARGET_PRICE")
    drive, sheets = progress.run("Connect Google APIs", clients)
    progress.run("Verify research Drive folder", verify_folder, drive, cfg.folder_id)
    reports = progress.run(
        "Load and parse report sheet",
        lambda: parse_reports(sheet_values(sheets, cfg.sheet_id, "基本面選股")),
    )
    def load_actions():
        try:
            return parse_actions(sheet_values(sheets, cfg.sheet_id, "CorporateActions"))
        except Exception as exc:
            if "Unable to parse range" not in str(exc):
                raise
            progress.diagnostic("corporate_actions", status="MISSING_OPTIONAL_SHEET")
            return parse_actions([])

    actions = progress.run("Load corporate-action input", load_actions)
    raw_close, raw_open, adj_close = progress.run("Load FinLab price datasets", load_finlab_prices)
    market_date = market_dates(raw_close)[-1]
    state = progress.run("Load persistent market state", read_state, drive, cfg.folder_id)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() or os.environ.get("GITHUB_REF_NAME", "detached")
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()

    last_state_date = state.get("last_successful_market_date")
    has_new_market_date = not last_state_date or market_date > pd.Timestamp(last_state_date)
    if last_state_date and market_date < pd.Timestamp(last_state_date):
        raise ValueError(f"FinLab latest market date {market_date.date()} is older than state last_successful_market_date {last_state_date}")

    progress.diagnostic(
        "input_data",
        reports=len(reports),
        corporate_actions=len(actions),
        raw_close_rows=len(raw_close),
        raw_close_columns=len(raw_close.columns),
        latest_market_date=market_date.date(),
        state_market_date=state.get("last_successful_market_date") or "NONE",
    )
    progress.run("Validate corporate-action coverage", check_action_coverage, reports, actions, raw_close, adj_close, market_date)
    current = progress.run("Screen current target-price universe", screen, reports, actions, raw_close, market_date, cfg.threshold, cfg.max_age_days)
    previous = progress.run("Load previous screen state", read_csv, drive, cfg.folder_id, "last_screen.csv", SCREEN_COLUMNS)
    previous_screen_market_date = progress.run("Validate previous state continuity", validate_previous_state, state, previous)
    ledger = progress.run("Load persistent signal ledger", read_csv, drive, cfg.folder_id, "signal_ledger.csv", LEDGER_COLUMNS)
    previous_ledger_rows = len(ledger)
    registry_before = progress.run("Load report registry", read_csv, drive, cfg.folder_id, "report_registry.csv", REGISTRY_COLUMNS)
    new_report_keys = progress.run("Identify newly observed reports", find_new_report_keys, reports, registry_before)
    registry = progress.run("Update report registry in memory", update_report_registry, reports, registry_before, now)
    new_reports = len(new_report_keys)

    # Every successful execution is the current official result. Signal IDs make
    # same-market-date reruns idempotent while allowing newly keyed reports to be
    # incorporated without advancing the FinLab market-date state.
    ledger = progress.run(
        "Generate idempotent signal events",
        generate_signals,
        current,
        previous,
        ledger,
        commit,
        now,
        cfg.threshold,
        new_report_keys=new_report_keys,
    )
    new_signals = len(ledger) - previous_ledger_rows
    run_status = "SUCCESS_NEW_DATA" if has_new_market_date else "DATA_NOT_UPDATED"

    progress.diagnostic(
        "signal_state",
        current_rows=len(current),
        previous_rows=len(previous),
        previous_ledger_rows=previous_ledger_rows,
        merged_ledger_rows=len(ledger),
        new_reports=new_reports,
        new_signals=new_signals,
        run_status=run_status,
    )
    returns = progress.run("Calculate forward outcomes", calculate_returns, ledger, raw_close, raw_open, adj_close)
    summary = progress.run("Build research summary", summarize, returns)
    candidates = progress.run("Build candidate presentation view", candidate_view, current)
    info = "\n".join([
        f"execution_timestamp={now}", "timezone=Asia/Taipei", f"git_commit={commit}", f"branch={branch}",
        f"run_status={run_status}", f"latest_finlab_market_date={market_date.date()}",
        f"last_successful_market_date={last_state_date or ''}", f"processed_market_date={market_date.date()}",
        f"previous_screen_market_date={previous_screen_market_date or ''}", f"previous_screen_rows={len(previous)}",
        f"previous_ledger_rows={previous_ledger_rows}", f"new_signals={new_signals}", f"new_reports={new_reports}",
        f"state_updated={'true' if has_new_market_date else 'false'}", "current_outputs_published=true",
        f"TARGET_UPSIDE_THRESHOLD={cfg.threshold}", f"REPORT_MAX_AGE_DAYS={cfg.max_age_days}",
        "price_source=FinLab raw price:收盤價; raw price:開盤價; adjusted etl:adj_close", "benchmark=0050",
        "data_validation=PASS; corporate action coverage heuristic >10% ratio jump plus manually classified events",
        "research_conclusion=修改後再測", ""
    ])
    frames = {"daily_screen.csv": current, "candidate.csv": candidates, "signal_ledger.csv": ledger, "signal_returns.csv": returns,
              "research_summary.csv": summary, "last_screen.csv": current, "report_snapshot.csv": reports,
              "report_registry.csv": registry, "corporate_actions_snapshot.csv": actions}
    name = progress.run("Archive execution outputs", archive, drive, cfg.folder_id, frames, info, commit)
    state_market_date = str(market_date.date()) if has_new_market_date else last_state_date
    progress.run(
        "Publish persistent state",
        put_file,
        drive,
        cfg.folder_id,
        "state.json",
        json.dumps({"last_successful_market_date": state_market_date, "last_archive": name}).encode(),
        "application/json",
        replace=True,
    )
    progress.finish(
        run_status,
        market_date=market_date.date(),
        archive=name,
        candidates=len(candidates),
        ledger_rows=len(ledger),
    )
    if has_new_market_date:
        print(f"SUCCESS: {name} market_date={market_date.date()} signals={len(ledger)}")
    else:
        print(f"DATA_NOT_UPDATED: {name} latest_available_market_date={market_date.date()}; last_successful_market_date={last_state_date}")
    return name

if __name__ == "__main__":
    run()
