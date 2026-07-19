import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest import mock

from prism_core.classroom import run_classroom_replay
from prism_core.ledger import Ledger
import runtime_config


_HOSTILE_OVERRIDES = {
    "LECTURE_DATA_MODE": "yfinance",
    "LECTURE_SCREENING_MODE": "real",
    "LECTURE_LLM_MODE": "openai",
    "LECTURE_REPORT_MODE": "research",
    "LECTURE_RESEARCH_TOOLS": "perplexity,firecrawl",
    "LECTURE_TRADE_MODE": "real",
    "LECTURE_BROKER": "kis",
    "LECTURE_BROKER_MODE": "real",
    "KIS_MODE": "real",
    "LECTURE_ENABLE_LIVE_BROKER": "1",
    "LECTURE_ALLOW_REAL_BROKER": "1",
    "OPENAI_API_KEY": "must-not-be-used",
    "PERPLEXITY_API_KEY": "must-not-be-used",
    "FIRECRAWL_API_KEY": "must-not-be-used",
}


class ClassroomReplayTest(unittest.TestCase):
    def test_replay_finishes_entry_hold_trailing_exit_for_kr_and_us(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"

            result = run_classroom_replay(path)

            self.assertEqual(result["cycles"], 3)
            self.assertEqual(result["final_positions"], 0)
            self.assertEqual(result["realized_trades"], 2)
            self.assertEqual(result["markets"], ["KR", "US"])
            with sqlite3.connect(path) as conn:
                exits = conn.execute(
                    "SELECT market,symbol,order_type,limit_price,reason "
                    "FROM broker_orders "
                    "WHERE side='SELL' ORDER BY market,symbol"
                ).fetchall()
            self.assertEqual(
                exits,
                [
                    ("KR", "005930", "MARKET", None, "trailing_stop"),
                    ("US", "AAPL", "MARKET", None, "trailing_stop"),
                ],
            )

    def test_completed_replay_on_same_db_counts_only_new_realized_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"

            first = run_classroom_replay(path)
            second = run_classroom_replay(path)

            self.assertEqual(first["realized_trades"], 2)
            self.assertEqual(second["realized_trades"], 2)
            self.assertEqual(second["final_positions"], 0)
            self.assertEqual(Ledger(path).count_realized_trades(), 4)
            with sqlite3.connect(path) as conn:
                fill_ids = [
                    row[0]
                    for row in conn.execute(
                        "SELECT fill_id FROM fills ORDER BY fill_id"
                    ).fetchall()
                ]
            self.assertEqual(len(fill_ids), 8)
            self.assertTrue(all(item.endswith(":auto-fill") for item in fill_ids))
            self.assertEqual(len(fill_ids), len(set(fill_ids)))

    def test_replay_uses_only_supplied_path_without_env_or_network_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "classroom.db"
            with mock.patch("os.getenv", side_effect=AssertionError("env lookup")), mock.patch.object(
                socket, "create_connection", side_effect=AssertionError("network lookup")
            ), mock.patch.object(
                socket, "socket", side_effect=AssertionError("network socket")
            ):
                result = run_classroom_replay(path)

            self.assertEqual(result["realized_trades"], 2)
            self.assertTrue(path.is_file())
            self.assertEqual(
                sorted(item.name for item in path.parent.iterdir()),
                ["classroom.db", "classroom.db.cycle-lock"],
            )

    def test_replay_fails_closed_when_cycle_fence_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)

            with ledger.cycle_fence() as acquired:
                self.assertTrue(acquired)
                with self.assertRaisesRegex(RuntimeError, "cycle_overlap"):
                    run_classroom_replay(path)

            self.assertEqual(ledger.count_realized_trades(), 0)


class ClassroomRuntimeProfileTest(unittest.TestCase):
    def test_classroom_backtest_and_aliases_are_fixed_offline_simulations(self):
        cases = {
            "classroom": "classroom",
            "class": "classroom",
            "replay": "classroom",
            "backtest": "backtest",
            "walk_forward": "backtest",
        }
        for supplied, expected in cases.items():
            with self.subTest(profile=supplied), mock.patch.dict(
                os.environ,
                {"LECTURE_PROFILE": supplied, **_HOSTILE_OVERRIDES},
                clear=True,
            ):
                cfg = runtime_config.load_runtime_config()

            self.assertEqual(cfg.profile, expected)
            self.assertEqual(cfg.data_mode, "mock")
            self.assertEqual(cfg.screening_mode, "mock")
            self.assertEqual(cfg.llm_mode, "mock")
            self.assertEqual(cfg.report_mode, "lite")
            self.assertEqual(cfg.research_tools, ())
            self.assertEqual(cfg.trade_mode, "simulation")
            self.assertEqual((cfg.broker, cfg.broker_mode), ("paper", "paper"))
            self.assertFalse(cfg.llm_enabled)
            self.assertFalse(cfg.live_broker_enabled)
            self.assertFalse(cfg.real_broker_allowed)
            self.assertTrue(runtime_config.resolve_trade_dry_run(True, False, cfg))

    def test_profile_choices_expose_canonical_names_and_aliases(self):
        for name in (
            "classroom",
            "class",
            "replay",
            "backtest",
            "walk_forward",
        ):
            self.assertIn(name, runtime_config.PROFILE_CHOICES)


if __name__ == "__main__":
    unittest.main()
