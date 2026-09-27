import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

from src.corporate_actions import effective_target, parse_actions
from src.price_loader import market_dates
from src.report_loader import latest_reports, parse_reports
from src.research_summary import summarize
from src.returns import calculate_returns
from src.screener import screen
from src.signal_ledger import LEDGER_COLUMNS, generate_signals


def reports():
    return parse_reports([["Ticker", "名稱", "報告日期", "前次目標價", "本次目標價", "投顧", "持有", "買進日期", "成本均價"], ["2330", "台積電", "2026-01-01", "120", "130", "B", "Y", "", "75"]])


def prices(dates, closes):
    index = pd.to_datetime(dates)
    return pd.DataFrame({"2330": closes, "0050": [100] * len(index)}, index=index)


class ResearchRules(unittest.TestCase):
    def setUp(self):
        self.reports = reports()
        self.actions = parse_actions([])

    def test_report_selection_and_future(self):
        other = reports()
        other.loc[:, "report_date"] = pd.Timestamp("2026-04-02")
        other.loc[:, "original_target_price"] = 200
        both = pd.concat([self.reports, other], ignore_index=True)
        self.assertEqual(latest_reports(both, "2026-04-01").iloc[0].original_target_price, 130)
        self.assertEqual(latest_reports(both, "2026-04-02").iloc[0].original_target_price, 200)
        with self.assertRaises(ValueError):
            parse_reports([["Ticker", "名稱", "報告日期", "本次目標價", "投顧"], ["2330", "A", "2026-01-01", "130", "B"], ["2330", "A", "2026-01-01", "140", "B"]])

    def test_age_boundary_upside_and_holding(self):
        frame = prices(["2026-04-01", "2026-04-02"], [100, 100])
        day90 = screen(self.reports, self.actions, frame, "2026-04-01")
        day91 = screen(self.reports, self.actions, frame, "2026-04-02")
        self.assertEqual(day90.iloc[0].report_age_days, 90)
        self.assertEqual(day90.iloc[0].screen_status, "ACTIVE_BELOW_THRESHOLD")
        self.assertEqual(day90.iloc[0].target_upside, .3)
        self.assertEqual(day91.iloc[0].screen_status, "EXPIRED")
        self.assertEqual(day91.iloc[0].holding_status, "Y")
        self.assertAlmostEqual(day90.iloc[0].holding_return, 1 / 3)

    def test_crossing_reentry_idempotency_and_raw_price(self):
        dates = pd.date_range("2026-01-01", periods=5)
        close = prices(dates, [110, 99, 90, 110, 90])
        adjusted = close * 10  # Must not enter the upside calculation.
        ledger = pd.DataFrame(columns=LEDGER_COLUMNS)
        previous = pd.DataFrame()
        counts = []
        for day in dates:
            current = screen(self.reports, self.actions, close, day)
            ledger = generate_signals(current, previous, ledger, "abc", "now")
            counts.append(len(ledger))
            previous = current
        self.assertEqual(counts, [0, 1, 1, 1, 2])
        self.assertEqual(len(generate_signals(previous, screen(self.reports, self.actions, close, dates[-2]), ledger, "abc", "now")), 2)
        self.assertGreater(screen(self.reports, self.actions, close, dates[1]).iloc[0].target_upside, .3)
        self.assertEqual(adjusted.at[dates[1], "2330"], 990)

    def test_action_scale_and_cash_dividend(self):
        actions = parse_actions([["ticker", "effective_date", "action_type", "target_factor"], ["2330", "2026-01-02", "SPLIT", "0.5"], ["2330", "2026-01-03", "CASH_DIVIDEND", "1"]])
        report = SimpleNamespace(ticker="2330", report_date=pd.Timestamp("2026-01-01"), original_target_price=710)
        self.assertEqual(effective_target(report, "2026-01-01", actions), 710)
        self.assertEqual(effective_target(report, "2026-01-03", actions), 355)
        with self.assertRaises(ValueError):
            parse_actions([["ticker", "effective_date", "action_type", "target_factor"], ["2330", "2026-01-02", "CASH_DIVIDEND", "0.5"]])

    def test_returns_entry_maturity_and_missing_data(self):
        dates = pd.date_range("2026-01-01", periods=62)
        raw_close = prices(dates, [100] * len(dates))
        raw_open = prices(dates, [100] * len(dates))
        raw_open.at[dates[1], "2330"] = 80
        adjusted = raw_close * 2
        ledger = pd.DataFrame([dict(signal_id="x", signal_date="2026-01-01", ticker="2330")])
        result = calculate_returns(ledger, raw_close.iloc[:5], raw_open.iloc[:5], adjusted.iloc[:5]).iloc[0]
        self.assertEqual(result.entry_date, "2026-01-02")
        self.assertEqual(result.entry_adj_open, 160)
        self.assertEqual(result.status_O1_C5, "PENDING")
        result = calculate_returns(ledger, raw_close.iloc[:21], raw_open.iloc[:21], adjusted.iloc[:21]).iloc[0]
        self.assertAlmostEqual(result.stock_return_O1_C5, .25)
        self.assertAlmostEqual(result.excess_return_O1_C5, .25)
        self.assertEqual(result.status_O1_C20, "MATURE")
        self.assertEqual(result.status_O1_C60, "PENDING")
        self.assertEqual(calculate_returns(ledger, raw_close, raw_open, adjusted).iloc[0].status_O1_C60, "MATURE")
        raw_open.at[dates[1], "2330"] = float("nan")
        with self.assertRaises(ValueError):
            calculate_returns(ledger, raw_close, raw_open, adjusted)

    def test_stale_calendar(self):
        frame = prices(["2026-01-01", "2026-01-02"], [100, 101])
        self.assertEqual(market_dates(frame)[-1], pd.Timestamp("2026-01-02"))
        summary = summarize(pd.DataFrame())
        self.assertTrue((summary.sample_status == "INSUFFICIENT").all())


if __name__ == "__main__":
    unittest.main()
