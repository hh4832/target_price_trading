import unittest
import json
from unittest.mock import Mock, patch
from datetime import date
from types import SimpleNamespace

import pandas as pd

from src.corporate_actions import effective_target, parse_actions
from src.price_loader import market_dates
from src.pipeline import run, validate_previous_state
from src.report_loader import latest_reports, parse_reports
from src.report_registry import REGISTRY_COLUMNS, find_new_report_keys, update_report_registry
from src.research_summary import summarize
from src.returns import calculate_returns
from src.screener import candidate_view, screen
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


    def test_new_report_candidate_is_distinct_and_idempotent(self):
        day = pd.Timestamp("2026-01-01")
        close = prices([day], [99])  # 130 / 99 - 1 > 30%
        current = screen(self.reports, self.actions, close, day)
        key = ("2330", "B", "2026-01-01")
        ledger = generate_signals(current, pd.DataFrame(), pd.DataFrame(columns=LEDGER_COLUMNS), "abc", "now", new_report_keys={key})
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.iloc[0].signal_type, "NEW_REPORT_CANDIDATE")
        rerun = generate_signals(current, current, ledger, "def", "later", new_report_keys=set())
        self.assertEqual(len(rerun), 1)
        self.assertEqual(rerun.iloc[0].signal_id, ledger.iloc[0].signal_id)

    def test_new_report_below_threshold_has_no_signal_then_crosses(self):
        dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
        close = prices(dates, [110, 99])
        first = screen(self.reports, self.actions, close, dates[0])
        key = ("2330", "B", "2026-01-01")
        ledger = generate_signals(first, pd.DataFrame(), pd.DataFrame(columns=LEDGER_COLUMNS), "abc", "now", new_report_keys={key})
        self.assertEqual(len(ledger), 0)
        second = screen(self.reports, self.actions, close, dates[1])
        ledger = generate_signals(second, first, ledger, "abc", "later", new_report_keys=set())
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.iloc[0].signal_type, "THRESHOLD_CROSSING")

    def test_registry_new_report_keys_only_returns_unseen_reports(self):
        registry = update_report_registry(self.reports, pd.DataFrame(columns=REGISTRY_COLUMNS), "2026-01-01T08:00:00+08:00")
        self.assertEqual(find_new_report_keys(self.reports, registry), set())
        second = self.reports.copy()
        second.loc[:, "report_date"] = pd.Timestamp("2026-01-02")
        combined = pd.concat([self.reports, second], ignore_index=True)
        self.assertEqual(find_new_report_keys(combined, registry), {("2330", "B", "2026-01-02")})


    def test_candidate_view_only_contains_current_candidates_sorted_by_upside(self):
        current = pd.DataFrame([
            dict(ticker="A", name="A", broker="B1", report_date="2026-01-01", effective_target_price=140, raw_close=100, target_upside=.40, report_age_days=1, screen_status="CANDIDATE"),
            dict(ticker="B", name="B", broker="B2", report_date="2026-01-01", effective_target_price=125, raw_close=100, target_upside=.25, report_age_days=1, screen_status="ACTIVE_BELOW_THRESHOLD"),
            dict(ticker="C", name="C", broker="B3", report_date="2026-01-01", effective_target_price=135, raw_close=100, target_upside=.35, report_age_days=1, screen_status="CANDIDATE"),
        ])
        result = candidate_view(current)
        self.assertEqual(list(result.ticker), ["A", "C"])
        self.assertEqual(list(result.target_upside), [.40, .35])
        self.assertEqual(list(result.columns), ["ticker", "name", "broker", "report_date", "effective_target_price", "raw_close", "target_upside", "report_age_days"])

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

    def test_state_integrity(self):
        previous = pd.DataFrame({"market_date": ["2026-01-02", "2026-01-02"]})
        state = {"last_successful_market_date": "2026-01-02"}
        self.assertEqual(validate_previous_state(state, previous), date(2026, 1, 2))

        with self.assertRaises(ValueError):
            validate_previous_state({"last_successful_market_date": "2026-01-01"}, previous)
        with self.assertRaises(ValueError):
            validate_previous_state(state, pd.DataFrame({"market_date": ["2026-01-01", "2026-01-02"]}))
        with self.assertRaises(ValueError):
            validate_previous_state(state, pd.DataFrame(columns=["market_date"]))
        with self.assertRaises(ValueError):
            validate_previous_state({}, previous)
        self.assertIsNone(validate_previous_state({}, pd.DataFrame(columns=["market_date"])))

    @patch("src.pipeline.archive")
    @patch("src.pipeline.subprocess.check_output")
    @patch("src.pipeline.read_state")
    @patch("src.pipeline.load_finlab_prices")
    @patch("src.pipeline.sheet_values")
    @patch("src.pipeline.verify_folder")
    @patch("src.pipeline.clients")
    def test_same_market_date_full_snapshot_without_state_update(self, mock_clients, mock_verify, mock_sheet_values, mock_load_prices, mock_read_state, mock_check_output, mock_archive):
        drive, sheets = Mock(), Mock()
        mock_clients.return_value = (drive, sheets)
        mock_sheet_values.side_effect = [[["Ticker", "名稱", "報告日期", "前次目標價", "本次目標價", "投顧", "持有", "買進日期", "成本均價"], ["2330", "台積電", "2026-01-01", "120", "130", "B", "Y", "", "75"]], []]
        frame = prices(["2026-01-02"], [100])
        mock_load_prices.return_value = (frame, frame, frame)
        mock_read_state.return_value = {"last_successful_market_date": "2026-01-02", "last_archive": "prior"}
        mock_check_output.side_effect = ["abc123\n", "main\n"]
        mock_archive.return_value = "20260103_080000_abc123"
        previous = screen(reports(), parse_actions([]), frame, "2026-01-02")
        with patch("src.pipeline.put_file") as mock_put_file, patch("src.pipeline.read_csv", side_effect=[previous, pd.DataFrame(columns=LEDGER_COLUMNS), pd.DataFrame(columns=REGISTRY_COLUMNS)]), patch("src.pipeline.generate_signals", side_effect=lambda current, previous, ledger, *args, **kwargs: ledger) as mock_generate:
            result = run()
        self.assertEqual(result, "20260103_080000_abc123")
        frames = mock_archive.call_args.args[2]
        self.assertEqual(set(frames), {"daily_screen.csv", "candidate.csv", "signal_ledger.csv", "signal_returns.csv", "research_summary.csv", "last_screen.csv", "report_snapshot.csv", "report_registry.csv", "corporate_actions_snapshot.csv"})
        self.assertIn("run_status=DATA_NOT_UPDATED", mock_archive.call_args.args[3])
        self.assertIn("state_updated=false", mock_archive.call_args.args[3])
        self.assertIn("new_signals=0", mock_archive.call_args.args[3])
        self.assertIn("new_reports=1", mock_archive.call_args.args[3])
        self.assertIn("current_outputs_published=true", mock_archive.call_args.args[3])
        mock_generate.assert_called_once()
        mock_put_file.assert_called_once()
        payload = json.loads(mock_put_file.call_args.args[3].decode())
        self.assertEqual(payload["last_successful_market_date"], "2026-01-02")
        self.assertEqual(payload["last_archive"], "20260103_080000_abc123")

    @patch("src.pipeline.archive")
    @patch("src.pipeline.subprocess.check_output")
    @patch("src.pipeline.read_state")
    @patch("src.pipeline.load_finlab_prices")
    @patch("src.pipeline.sheet_values")
    @patch("src.pipeline.verify_folder")
    @patch("src.pipeline.clients")
    def test_new_market_date_publishes_state(self, mock_clients, mock_verify, mock_sheet_values, mock_load_prices, mock_read_state, mock_check_output, mock_archive):
        drive, sheets = Mock(), Mock()
        mock_clients.return_value = (drive, sheets)
        mock_sheet_values.side_effect = [[["Ticker", "名稱", "報告日期", "前次目標價", "本次目標價", "投顧", "持有", "買進日期", "成本均價"], ["2330", "台積電", "2026-01-01", "120", "130", "B", "Y", "", "75"]], []]
        frame = prices(["2026-01-01", "2026-01-02"], [110, 99])
        mock_load_prices.return_value = (frame, frame, frame)
        mock_read_state.return_value = {"last_successful_market_date": "2026-01-01", "last_archive": "prior"}
        mock_check_output.side_effect = ["abc123\n", "main\n"]
        mock_archive.return_value = "20260102_080000_abc123"
        previous = screen(reports(), parse_actions([]), frame, "2026-01-01")
        with patch("src.pipeline.put_file") as mock_put_file, patch("src.pipeline.read_csv", side_effect=[previous, pd.DataFrame(columns=LEDGER_COLUMNS), pd.DataFrame(columns=REGISTRY_COLUMNS)]):
            run()
        self.assertIn("run_status=SUCCESS_NEW_DATA", mock_archive.call_args.args[3])
        self.assertIn("state_updated=true", mock_archive.call_args.args[3])
        payload = json.loads(mock_put_file.call_args.args[3].decode())
        self.assertEqual(payload["last_successful_market_date"], "2026-01-02")

    def test_report_registry_preserves_first_seen_at(self):
        initial = update_report_registry(self.reports, pd.DataFrame(columns=REGISTRY_COLUMNS), "2026-09-30T04:51:00+08:00")
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial.iloc[0].first_seen_at, "2026-09-30T04:51:00+08:00")
        rerun = update_report_registry(self.reports, initial, "2026-09-30T05:30:00+08:00")
        self.assertEqual(len(rerun), 1)
        self.assertEqual(rerun.iloc[0].first_seen_at, "2026-09-30T04:51:00+08:00")

        added = self.reports.copy()
        second = self.reports.copy()
        second.loc[:, "report_date"] = pd.Timestamp("2026-09-29")
        added = pd.concat([added, second], ignore_index=True)
        updated = update_report_registry(added, rerun, "2026-09-30T06:00:00+08:00")
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated.loc[updated.report_date == "2026-09-29", "first_seen_at"].iloc[0], "2026-09-30T06:00:00+08:00")

    def test_stale_calendar(self):
        frame = prices(["2026-01-01", "2026-01-02"], [100, 101])
        self.assertEqual(market_dates(frame)[-1], pd.Timestamp("2026-01-02"))
        summary = summarize(pd.DataFrame())
        self.assertTrue((summary.sample_status == "INSUFFICIENT").all())


if __name__ == "__main__":
    unittest.main()
