"""Regression checks for automatic cron retry deduplication."""
import unittest

from src.pipeline import should_skip_redundant_automatic_run


class AutomaticScheduleGuardTests(unittest.TestCase):
    def test_skip_completed_automatic_runs_without_new_reports(self):
        state = {"last_archive": "20261019_040000_abcdef"}
        for event in ("schedule", "repository_dispatch"):
            with self.subTest(event=event):
                self.assertTrue(
                    should_skip_redundant_automatic_run(event, False, set(), state)
                )

    def test_new_market_date_is_not_skipped(self):
        self.assertFalse(
            should_skip_redundant_automatic_run(
                "repository_dispatch", True, set(), {"last_archive": "old"}
            )
        )

    def test_new_report_is_not_skipped(self):
        self.assertFalse(
            should_skip_redundant_automatic_run(
                "schedule", False, {("2330", "B", "2026-10-19")}, {"last_archive": "old"}
            )
        )

    def test_manual_and_local_runs_are_not_skipped(self):
        for event in ("workflow_dispatch", "push", ""):
            with self.subTest(event=event):
                self.assertFalse(
                    should_skip_redundant_automatic_run(
                        event, False, set(), {"last_archive": "old"}
                    )
                )

    def test_missing_success_archive_is_not_skipped(self):
        self.assertFalse(
            should_skip_redundant_automatic_run(
                "repository_dispatch", False, set(), {"last_successful_market_date": "2026-10-19"}
            )
        )


if __name__ == "__main__":
    unittest.main()
