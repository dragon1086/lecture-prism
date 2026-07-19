import os
from pathlib import Path
from decimal import Decimal
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

import prism_core.classroom as classroom
from prism_core.classroom import run_classroom_replay
from prism_core.domain import Market, OrderIntent, OrderSide, OrderType
from prism_core.ledger import Ledger
from prism_core.paper_broker import PaperBroker
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

    def test_concurrent_replays_receive_distinct_persisted_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            first_entered = threading.Event()
            release_first = threading.Event()
            results = []
            errors = []
            real_run = classroom.TradingCycle.run

            def controlled_run(cycle, run_id, intents, *, auto_fill=False):
                if (
                    threading.current_thread().name == "first-replay"
                    and run_id.endswith("-1")
                ):
                    first_entered.set()
                    if not release_first.wait(2):
                        raise TimeoutError("first replay was not released")
                return real_run(
                    cycle, run_id, intents, auto_fill=auto_fill
                )

            def invoke():
                try:
                    results.append(run_classroom_replay(path))
                except Exception as exc:
                    errors.append(exc)

            with mock.patch.object(
                classroom.TradingCycle, "run", new=controlled_run
            ):
                first = threading.Thread(target=invoke, name="first-replay")
                second = threading.Thread(target=invoke, name="second-replay")
                first.start()
                self.assertTrue(first_entered.wait(2))
                second.start()
                time.sleep(0.05)
                self.assertTrue(second.is_alive())
                release_first.set()
                first.join(3)
                second.join(3)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertEqual(
                {result["session"] for result in results},
                {"classroom-000001", "classroom-000002"},
            )
            self.assertTrue(
                all(result["realized_trades"] == 2 for result in results)
            )
            self.assertEqual(Ledger(path).count_realized_trades(), 4)
            with sqlite3.connect(path) as conn:
                rows = conn.execute(
                    "SELECT session_id,status,realized_trades "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("classroom-000001", "COMPLETED", 2),
                    ("classroom-000002", "COMPLETED", 2),
                ],
            )

    def test_partial_exit_failure_retries_same_session_to_complete_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            injected = False

            def fail_after_first_exit(
                broker, client_order_id, execution_key, quantity, price
            ):
                nonlocal injected
                record = real_fill(
                    broker,
                    client_order_id,
                    execution_key,
                    quantity,
                    price,
                )
                if (
                    not injected
                    and record.intent.side is OrderSide.SELL
                    and record.intent.market is Market.KR
                ):
                    injected = True
                    raise RuntimeError("injected after committed KR exit")
                return record

            with mock.patch.object(
                PaperBroker, "fill_order", new=fail_after_first_exit
            ):
                with self.assertRaisesRegex(RuntimeError, "committed KR exit"):
                    run_classroom_replay(path)

            retry = run_classroom_replay(path)

            self.assertEqual(retry["session"], "classroom-000001")
            self.assertEqual(retry["realized_trades"], 2)
            self.assertEqual(retry["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                rows = conn.execute(
                    "SELECT session_id,status,owner_token,realized_trades "
                    "FROM classroom_replays"
                ).fetchall()
            self.assertEqual(
                rows,
                [("classroom-000001", "COMPLETED", None, 2)],
            )

    def test_unrelated_position_is_never_counted_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            broker = PaperBroker(Ledger(path))
            unrelated = OrderIntent(
                "user:US:MSFT:BUY",
                Market.US,
                "MSFT",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("300"),
                "USD",
                strategy_id="user_strategy",
            )
            broker.submit_order(unrelated)
            broker.fill_order(
                unrelated.client_order_id,
                "user-fill",
                unrelated.quantity,
                unrelated.limit_price,
            )

            result = run_classroom_replay(path)

            self.assertEqual(result["final_positions"], 0)
            positions = Ledger(path).list_positions()
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].symbol, "MSFT")
            self.assertEqual(positions[0].strategy_id, "user_strategy")

    def test_unrelated_target_position_fails_closed_without_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            broker = PaperBroker(Ledger(path))
            unrelated = OrderIntent(
                "user:US:AAPL:BUY",
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("180"),
                "USD",
                strategy_id="user_strategy",
            )
            broker.submit_order(unrelated)
            broker.fill_order(
                unrelated.client_order_id,
                "user-fill",
                unrelated.quantity,
                unrelated.limit_price,
            )

            with self.assertRaisesRegex(RuntimeError, "unrelated position"):
                run_classroom_replay(path)

            positions = Ledger(path).list_positions()
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].strategy_id, "user_strategy")

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
                [
                    "classroom.db",
                    "classroom.db.classroom-replay-lock",
                    "classroom.db.cycle-lock",
                ],
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

    def test_replay_fails_closed_when_replay_lease_cannot_be_acquired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "other-owner", lease_seconds=60
            )
            self.assertIsNotNone(claim)

            with mock.patch.object(classroom, "_REPLAY_WAIT_SECONDS", 0):
                with self.assertRaisesRegex(RuntimeError, "lease unavailable"):
                    run_classroom_replay(path)

            ledger.release_classroom_replay(claim)

    def test_replay_fails_closed_when_replay_wide_fence_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)

            with ledger.classroom_replay_fence(wait_seconds=0) as acquired:
                self.assertTrue(acquired)
                with mock.patch.object(classroom, "_REPLAY_WAIT_SECONDS", 0):
                    with self.assertRaisesRegex(
                        RuntimeError, "replay fence unavailable"
                    ):
                        run_classroom_replay(path)

    def test_expired_replay_lease_is_reclaimed_with_same_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "classroom.db")
            first = ledger.claim_classroom_replay(
                "dead-owner", lease_seconds=10, now=100
            )

            active = ledger.claim_classroom_replay(
                "new-owner", lease_seconds=10, now=109
            )
            reclaimed = ledger.claim_classroom_replay(
                "new-owner", lease_seconds=10, now=111
            )

            self.assertIsNone(active)
            self.assertEqual(reclaimed.session_id, first.session_id)
            self.assertEqual(reclaimed.strategy_id, first.strategy_id)
            ledger.release_classroom_replay(reclaimed)


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

    def test_runtime_config_scope_is_isolated_across_async_tasks_and_resets(self):
        import asyncio

        classroom_cfg = runtime_config.load_runtime_config("classroom")
        research_cfg = runtime_config.load_runtime_config("research")

        async def observe(cfg):
            with runtime_config.runtime_config_scope(cfg):
                await asyncio.sleep(0)
                return runtime_config.load_runtime_config().profile

        async def run_observers():
            return await asyncio.gather(
                observe(classroom_cfg),
                observe(research_cfg),
            )

        observed = asyncio.run(run_observers())

        self.assertEqual(observed, ["classroom", "research"])
        self.assertNotEqual(
            runtime_config.load_runtime_config().profile,
            "classroom",
        )


if __name__ == "__main__":
    unittest.main()
