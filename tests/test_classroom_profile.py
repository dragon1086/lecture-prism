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
from prism_core.domain import (
    Market,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
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

    def test_accepted_exit_retry_resumes_at_trailing_quote_after_expired_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            injected = False

            def fail_before_first_exit_fill(
                broker, client_order_id, execution_key, quantity, price
            ):
                nonlocal injected
                order = broker.get_order(client_order_id)
                if (
                    not injected
                    and order.intent.side is OrderSide.SELL
                    and order.intent.market is Market.KR
                ):
                    injected = True
                    self.assertEqual(order.status.value, "ACCEPTED")
                    raise RuntimeError("injected before accepted KR exit fill")
                return real_fill(
                    broker,
                    client_order_id,
                    execution_key,
                    quantity,
                    price,
                )

            with mock.patch.object(
                PaperBroker, "fill_order", new=fail_before_first_exit_fill
            ):
                with self.assertRaisesRegex(RuntimeError, "accepted KR exit"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                before_retry = conn.execute(
                    "SELECT status FROM classroom_replays"
                ).fetchone()
                accepted = conn.execute(
                    "SELECT status FROM broker_orders "
                    "WHERE client_order_id=?",
                    ("classroom-000001-3:KR:005930:SELL",),
                ).fetchone()
                conn.execute(
                    "UPDATE classroom_replays SET owner_token='dead-owner',"
                    "lease_expires_at=0 WHERE session_id='classroom-000001'"
                )

            self.assertEqual(before_retry, ("INCOMPLETE",))
            self.assertEqual(accepted, ("ACCEPTED",))

            retry = run_classroom_replay(path)

            self.assertEqual(retry["session"], "classroom-000001")
            with sqlite3.connect(path) as conn:
                trades = conn.execute(
                    "SELECT market,symbol,quantity,exit_price,currency "
                    "FROM realized_trades ORDER BY market,symbol"
                ).fetchall()
            self.assertEqual(
                trades,
                [
                    ("KR", "005930", "1", "69000", "KRW"),
                    ("US", "AAPL", "1", "175", "USD"),
                ],
            )
            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,owner_token,realized_trades "
                    "FROM classroom_replays"
                ).fetchone()
            self.assertEqual(replay, ("COMPLETED", 4, None, 2))

    def test_checkpoint_failures_before_and_after_write_are_idempotent(self):
        real_advance = Ledger.advance_classroom_replay_phase
        cases = ((3, False), (1, True))

        for failed_phase, fail_after_write in cases:
            with self.subTest(
                failed_phase=failed_phase,
                fail_after_write=fail_after_write,
            ), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "classroom.db"
                injected = False

                def fail_once(
                    ledger,
                    claim,
                    *,
                    expected_phase,
                    next_phase,
                ):
                    nonlocal injected
                    if not injected and expected_phase == failed_phase:
                        injected = True
                        if fail_after_write:
                            real_advance(
                                ledger,
                                claim,
                                expected_phase=expected_phase,
                                next_phase=next_phase,
                            )
                        raise RuntimeError("injected checkpoint failure")
                    return real_advance(
                        ledger,
                        claim,
                        expected_phase=expected_phase,
                        next_phase=next_phase,
                    )

                with mock.patch.object(
                    Ledger,
                    "advance_classroom_replay_phase",
                    new=fail_once,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "checkpoint failure"
                    ):
                        run_classroom_replay(path)

                retry = run_classroom_replay(path)

                self.assertEqual(retry["session"], "classroom-000001")
                with sqlite3.connect(path) as conn:
                    replay = conn.execute(
                        "SELECT status,phase,realized_trades "
                        "FROM classroom_replays"
                    ).fetchone()
                    trades = conn.execute(
                        "SELECT market,symbol,exit_price "
                        "FROM realized_trades ORDER BY market,symbol"
                    ).fetchall()
                self.assertEqual(replay, ("COMPLETED", 4, 2))
                self.assertEqual(
                    trades,
                    [("KR", "005930", "69000"), ("US", "AAPL", "175")],
                )

    def test_completion_rejects_wrong_attributed_exit_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            wrong_quotes = dict(classroom._TRAILING_EXIT_QUOTES)
            wrong_quotes[(Market.KR, "005930")] = Decimal("68000")

            with mock.patch.object(
                classroom, "_TRAILING_EXIT_QUOTES", wrong_quotes
            ):
                with self.assertRaisesRegex(RuntimeError, "trade contract"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,realized_trades "
                    "FROM classroom_replays"
                ).fetchone()
            self.assertEqual(replay, ("INCOMPLETE", 4, 0))

    def test_legacy_wrong_trade_is_aborted_and_fresh_sessions_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            wrong_quotes = dict(classroom._TRAILING_EXIT_QUOTES)
            wrong_quotes[(Market.KR, "005930")] = Decimal("68000")
            old_strategy = "classroom-replay:classroom-000001"

            with mock.patch.object(
                classroom, "_TRAILING_EXIT_QUOTES", wrong_quotes
            ):
                with self.assertRaisesRegex(RuntimeError, "trade contract"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE realized_trades SET exit_price='70000' "
                    "WHERE strategy_id=? AND market='KR'",
                    (old_strategy,),
                )
                conn.execute("ALTER TABLE classroom_replays DROP COLUMN phase")
                old_trades = conn.execute(
                    "SELECT market,symbol,quantity,exit_price,currency "
                    "FROM realized_trades WHERE strategy_id=? "
                    "ORDER BY market,symbol",
                    (old_strategy,),
                ).fetchall()
                old_orders = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? ORDER BY client_order_id",
                    (old_strategy,),
                ).fetchall()

            recovered = run_classroom_replay(path)
            following = run_classroom_replay(path)

            self.assertEqual(recovered["session"], "classroom-000002")
            self.assertEqual(recovered["realized_trades"], 2)
            self.assertEqual(recovered["final_positions"], 0)
            self.assertEqual(following["session"], "classroom-000003")
            with sqlite3.connect(path) as conn:
                replays = conn.execute(
                    "SELECT session_id,status,abort_reason,aborted_at "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
                preserved_trades = conn.execute(
                    "SELECT market,symbol,quantity,exit_price,currency "
                    "FROM realized_trades WHERE strategy_id=? "
                    "ORDER BY market,symbol",
                    (old_strategy,),
                ).fetchall()
                preserved_orders = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? ORDER BY client_order_id",
                    (old_strategy,),
                ).fetchall()
                canonical = conn.execute(
                    "SELECT strategy_id,market,symbol,exit_price "
                    "FROM realized_trades WHERE strategy_id<>? "
                    "ORDER BY strategy_id,market,symbol",
                    (old_strategy,),
                ).fetchall()

            self.assertEqual(
                [(row[0], row[1]) for row in replays],
                [
                    ("classroom-000001", "ABORTED"),
                    ("classroom-000002", "COMPLETED"),
                    ("classroom-000003", "COMPLETED"),
                ],
            )
            self.assertEqual(replays[0][2], "noncanonical_realized_trade")
            self.assertIsNotNone(replays[0][3])
            self.assertEqual(preserved_trades, old_trades)
            self.assertEqual(preserved_orders, old_orders)
            self.assertEqual(
                canonical,
                [
                    (
                        "classroom-replay:classroom-000002",
                        "KR",
                        "005930",
                        "69000",
                    ),
                    (
                        "classroom-replay:classroom-000002",
                        "US",
                        "AAPL",
                        "175",
                    ),
                    (
                        "classroom-replay:classroom-000003",
                        "KR",
                        "005930",
                        "69000",
                    ),
                    (
                        "classroom-replay:classroom-000003",
                        "US",
                        "AAPL",
                        "175",
                    ),
                ],
            )

    def test_legacy_wrong_partial_exit_is_quarantined_without_history_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            old_strategy = "classroom-replay:classroom-000001"
            injected = False

            def commit_legacy_wrong_kr_exit(
                broker, client_order_id, execution_key, quantity, price
            ):
                nonlocal injected
                order = broker.get_order(client_order_id)
                if (
                    not injected
                    and order.intent.side is OrderSide.SELL
                    and order.intent.market is Market.KR
                ):
                    injected = True
                    real_fill(
                        broker,
                        client_order_id,
                        execution_key,
                        quantity,
                        Decimal("70000"),
                    )
                    raise RuntimeError("legacy wrong partial exit")
                return real_fill(
                    broker,
                    client_order_id,
                    execution_key,
                    quantity,
                    price,
                )

            with mock.patch.object(
                PaperBroker, "fill_order", new=commit_legacy_wrong_kr_exit
            ):
                with self.assertRaisesRegex(RuntimeError, "wrong partial"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                conn.execute("ALTER TABLE classroom_replays DROP COLUMN phase")
                old_orders = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? ORDER BY client_order_id",
                    (old_strategy,),
                ).fetchall()
                old_trades = conn.execute(
                    "SELECT market,symbol,exit_price FROM realized_trades "
                    "WHERE strategy_id=? ORDER BY market,symbol",
                    (old_strategy,),
                ).fetchall()
                old_positions = conn.execute(
                    "SELECT market,symbol FROM positions "
                    "WHERE strategy_id=? ORDER BY market,symbol",
                    (old_strategy,),
                ).fetchall()

            self.assertEqual(old_trades, [("KR", "005930", "70000")])
            self.assertEqual(old_positions, [("US", "AAPL")])

            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000002")
            self.assertEqual(result["realized_trades"], 2)
            self.assertEqual(result["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                replay_rows = conn.execute(
                    "SELECT session_id,status FROM classroom_replays "
                    "ORDER BY sequence"
                ).fetchall()
                preserved_prefix = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? AND client_order_id<>? "
                    "ORDER BY client_order_id",
                    (
                        old_strategy,
                        "classroom-000001-3:US:AAPL:SELL",
                    ),
                ).fetchall()
                quarantined_trades = conn.execute(
                    "SELECT market,symbol,exit_price FROM realized_trades "
                    "WHERE strategy_id=? ORDER BY market,symbol",
                    (old_strategy,),
                ).fetchall()
                positions = conn.execute(
                    "SELECT COUNT(*) FROM positions"
                ).fetchone()[0]

            self.assertEqual(
                replay_rows,
                [
                    ("classroom-000001", "ABORTED"),
                    ("classroom-000002", "COMPLETED"),
                ],
            )
            self.assertEqual(preserved_prefix, old_orders)
            self.assertEqual(
                quarantined_trades,
                [
                    ("KR", "005930", "70000"),
                    ("US", "AAPL", "175"),
                ],
            )
            self.assertEqual(positions, 0)

    def test_legacy_null_provenance_partial_exit_cleans_residual_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            old_strategy = "classroom-replay:classroom-000001"
            interrupted = False

            def interrupt_after_kr_exit(
                broker, client_order_id, execution_key, quantity, price
            ):
                nonlocal interrupted
                order = broker.get_order(client_order_id)
                result = real_fill(
                    broker,
                    client_order_id,
                    execution_key,
                    quantity,
                    price,
                )
                if (
                    not interrupted
                    and order.intent.side is OrderSide.SELL
                    and order.intent.market is Market.KR
                ):
                    interrupted = True
                    raise RuntimeError("pre-R7 partial replay")
                return result

            with mock.patch.object(
                PaperBroker,
                "fill_order",
                new=interrupt_after_kr_exit,
            ):
                with self.assertRaisesRegex(RuntimeError, "pre-R7"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE realized_trades SET "
                    "exit_client_order_id=NULL,exit_fill_id=NULL "
                    "WHERE strategy_id=? AND market='KR'",
                    (old_strategy,),
                )
                preserved_kr_trade = conn.execute(
                    "SELECT id,market,symbol,quantity,entry_price,"
                    "exit_price,pnl_amount,currency,strategy_id,closed_at "
                    "FROM realized_trades WHERE strategy_id=? "
                    "AND market='KR'",
                    (old_strategy,),
                ).fetchone()
                residual = conn.execute(
                    "SELECT market,symbol,strategy_id FROM positions"
                ).fetchall()
            self.assertEqual(
                residual,
                [("US", "AAPL", old_strategy)],
            )

            try:
                recovered = run_classroom_replay(path)
            except RuntimeError as exc:
                self.fail(f"legacy residual cleanup remained blocked: {exc}")
            following = run_classroom_replay(path)

            self.assertEqual(
                (recovered["session"], recovered["realized_trades"]),
                ("classroom-000002", 2),
            )
            self.assertEqual(recovered["final_positions"], 0)
            self.assertEqual(
                (following["session"], following["realized_trades"]),
                ("classroom-000003", 2),
            )
            self.assertEqual(following["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                replays = conn.execute(
                    "SELECT session_id,status,abort_reason,realized_trades "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
                current_kr_trade = conn.execute(
                    "SELECT id,market,symbol,quantity,entry_price,"
                    "exit_price,pnl_amount,currency,strategy_id,closed_at "
                    "FROM realized_trades WHERE strategy_id=? "
                    "AND market='KR'",
                    (old_strategy,),
                ).fetchone()
                old_trades = conn.execute(
                    "SELECT market,exit_price,exit_client_order_id,"
                    "exit_fill_id FROM realized_trades WHERE strategy_id=? "
                    "ORDER BY market",
                    (old_strategy,),
                ).fetchall()
                old_exits = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? AND side='SELL' "
                    "ORDER BY client_order_id",
                    (old_strategy,),
                ).fetchall()
                positions = conn.execute(
                    "SELECT COUNT(*) FROM positions"
                ).fetchone()[0]

            self.assertEqual(
                replays,
                [
                    (
                        "classroom-000001",
                        "ABORTED",
                        "noncanonical_trade_provenance",
                        1,
                    ),
                    ("classroom-000002", "COMPLETED", None, 2),
                    ("classroom-000003", "COMPLETED", None, 2),
                ],
            )
            self.assertEqual(current_kr_trade, preserved_kr_trade)
            self.assertEqual(old_trades[0], ("KR", "69000", None, None))
            self.assertEqual(
                old_trades[1][0:3],
                (
                    "US",
                    "175",
                    "classroom-000001-3:US:AAPL:SELL",
                ),
            )
            self.assertIsNotNone(old_trades[1][3])
            self.assertEqual(
                old_exits,
                [
                    ("classroom-000001-3:KR:005930:SELL", "FILLED"),
                    ("classroom-000001-3:US:AAPL:SELL", "FILLED"),
                ],
            )
            self.assertEqual(positions, 0)

    def test_unrelated_unresolved_target_order_blocks_before_replay_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            broker = PaperBroker(Ledger(path))
            unrelated = OrderIntent(
                "user:US:AAPL:BUY:pending",
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

            with self.assertRaisesRegex(
                RuntimeError, "unrelated unresolved target order"
            ):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay_count = conn.execute(
                    "SELECT COUNT(*) FROM classroom_replays"
                ).fetchone()[0]
                order_before_cancel = conn.execute(
                    "SELECT status FROM broker_orders "
                    "WHERE client_order_id=?",
                    (unrelated.client_order_id,),
                ).fetchone()
                events_before_cancel = conn.execute(
                    "SELECT status FROM order_events "
                    "WHERE client_order_id=? ORDER BY id",
                    (unrelated.client_order_id,),
                ).fetchall()

            self.assertEqual(replay_count, 0)
            self.assertEqual(order_before_cancel, ("ACCEPTED",))
            self.assertEqual(
                events_before_cancel,
                [
                    ("CREATED",),
                    ("PREVIEWED",),
                    ("SUBMITTED",),
                    ("ACCEPTED",),
                ],
            )

            broker.cancel_order(unrelated.client_order_id)
            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)
            self.assertEqual(result["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                user_order = conn.execute(
                    "SELECT status FROM broker_orders "
                    "WHERE client_order_id=?",
                    (unrelated.client_order_id,),
                ).fetchone()
                canceled_event = conn.execute(
                    "SELECT COUNT(*) FROM order_events "
                    "WHERE client_order_id=? AND status='CANCELED'",
                    (unrelated.client_order_id,),
                ).fetchone()[0]
            self.assertEqual(user_order, ("CANCELED",))
            self.assertEqual(canceled_event, 1)

    def test_existing_phase_four_replay_waits_for_conflict_then_rederives_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            injected = False

            def stop_after_kr_exit(
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
                    raise RuntimeError("injected partial canonical replay")
                return record

            with mock.patch.object(
                PaperBroker, "fill_order", new=stop_after_kr_exit
            ):
                with self.assertRaisesRegex(RuntimeError, "partial canonical"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE classroom_replays SET phase=4 "
                    "WHERE session_id='classroom-000001'"
                )

            broker = PaperBroker(Ledger(path))
            unrelated = OrderIntent(
                "user:US:AAPL:BUY:late-conflict",
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

            with self.assertRaisesRegex(
                RuntimeError, "unrelated unresolved target order"
            ):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                blocked = conn.execute(
                    "SELECT status,phase,owner_token "
                    "FROM classroom_replays"
                ).fetchone()
            self.assertEqual(blocked, ("INCOMPLETE", 4, None))

            broker.cancel_order(unrelated.client_order_id)
            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)
            self.assertEqual(result["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase FROM classroom_replays"
                ).fetchone()
                exits = conn.execute(
                    "SELECT market,symbol,exit_price FROM realized_trades "
                    "WHERE strategy_id='classroom-replay:classroom-000001' "
                    "ORDER BY market,symbol"
                ).fetchall()
            self.assertEqual(replay, ("COMPLETED", 4))
            self.assertEqual(
                exits,
                [("KR", "005930", "69000"), ("US", "AAPL", "175")],
            )

    def test_canonical_unknown_entry_blocks_all_replay_work_until_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "setup-owner", lease_seconds=60
            )
            unknown_id = "classroom-000001-1:US:AAPL:BUY"
            intent = OrderIntent(
                unknown_id,
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("180"),
                "USD",
                strategy_id=claim.strategy_id,
            )
            broker = PaperBroker(ledger)
            broker.submit_order(intent)
            broker.mark_unknown(unknown_id)
            ledger.release_classroom_replay(claim)

            for _ in range(2):
                with self.assertRaisesRegex(
                    RuntimeError, "UNKNOWN target order"
                ):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,owner_token FROM classroom_replays"
                ).fetchone()
                orders = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "ORDER BY client_order_id"
                ).fetchall()
                fills = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
                trades = conn.execute(
                    "SELECT COUNT(*) FROM realized_trades"
                ).fetchone()[0]
                positions = conn.execute(
                    "SELECT COUNT(*) FROM positions"
                ).fetchone()[0]

            self.assertEqual(replay, ("INCOMPLETE", 1, None))
            self.assertEqual(orders, [(unknown_id, "UNKNOWN")])
            self.assertEqual((fills, trades, positions), (0, 0, 0))

            ledger.transition_order(unknown_id, OrderStatus.CANCELED)
            successor_id = f"{unknown_id}:retry-1"
            real_fill = PaperBroker.fill_order
            injected = False

            def lose_successor_response(
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
                if not injected and client_order_id == successor_id:
                    injected = True
                    raise RuntimeError("lost entry successor response")
                return record

            with mock.patch.object(
                PaperBroker, "fill_order", new=lose_successor_response
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "entry successor response"
                ):
                    run_classroom_replay(path)

            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)
            self.assertEqual(result["final_positions"], 0)
            with sqlite3.connect(path) as conn:
                aapl_entries = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE market='US' AND symbol='AAPL' AND side='BUY' "
                    "ORDER BY client_order_id"
                ).fetchall()
            self.assertEqual(
                aapl_entries,
                [
                    (unknown_id, "CANCELED"),
                    (successor_id, "FILLED"),
                ],
            )

    def test_canonical_unknown_exit_uses_persisted_successor_after_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_fill = PaperBroker.fill_order
            unknown_id = "classroom-000001-3:KR:005930:SELL"
            injected = False

            def mark_kr_exit_unknown(
                broker, client_order_id, execution_key, quantity, price
            ):
                nonlocal injected
                if not injected and client_order_id == unknown_id:
                    injected = True
                    broker.mark_unknown(client_order_id)
                    raise RuntimeError("injected UNKNOWN exit")
                return real_fill(
                    broker,
                    client_order_id,
                    execution_key,
                    quantity,
                    price,
                )

            with mock.patch.object(
                PaperBroker, "fill_order", new=mark_kr_exit_unknown
            ):
                with self.assertRaisesRegex(RuntimeError, "UNKNOWN exit"):
                    run_classroom_replay(path)

            with self.assertRaisesRegex(RuntimeError, "UNKNOWN target order"):
                run_classroom_replay(path)

            ledger = Ledger(path)
            ledger.transition_order(unknown_id, OrderStatus.CANCELED)
            successor_id = f"{unknown_id}:retry-1"
            injected = False

            def lose_exit_successor_response(
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
                if not injected and client_order_id == successor_id:
                    injected = True
                    raise RuntimeError("lost exit successor response")
                return record

            with mock.patch.object(
                PaperBroker, "fill_order", new=lose_exit_successor_response
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "exit successor response"
                ):
                    run_classroom_replay(path)

            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)
            with sqlite3.connect(path) as conn:
                kr_exits = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE market='KR' AND symbol='005930' AND side='SELL' "
                    "ORDER BY client_order_id"
                ).fetchall()
                prices = conn.execute(
                    "SELECT market,exit_price FROM realized_trades "
                    "ORDER BY market"
                ).fetchall()
            self.assertEqual(
                kr_exits,
                [
                    (unknown_id, "CANCELED"),
                    (successor_id, "FILLED"),
                ],
            )
            self.assertEqual(prices, [("KR", "69000"), ("US", "175")])

    def test_same_strategy_noncanonical_unresolved_order_blocks_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "setup-owner", lease_seconds=60
            )
            spoof = OrderIntent(
                "classroom-000001-1:US:AAPL:BUY:spoof",
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("180"),
                "USD",
                strategy_id=claim.strategy_id,
            )
            PaperBroker(ledger).submit_order(spoof)
            ledger.release_classroom_replay(claim)

            with self.assertRaisesRegex(
                RuntimeError, "noncanonical replay order"
            ):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT phase,owner_token FROM classroom_replays"
                ).fetchone()
                orders = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders"
                ).fetchall()
            self.assertEqual(replay, (1, None))
            self.assertEqual(orders, [(spoof.client_order_id, "ACCEPTED")])

    def test_predicted_fresh_strategy_order_never_authorizes_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            predicted = OrderIntent(
                "classroom-000001-1:KR:005930:BUY",
                Market.KR,
                "005930",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("70000"),
                "KRW",
                strategy_id="classroom-replay:classroom-000001",
            )
            PaperBroker(ledger).submit_order(predicted)

            with self.assertRaisesRegex(
                RuntimeError, "unrelated unresolved target order"
            ):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay_count = conn.execute(
                    "SELECT COUNT(*) FROM classroom_replays"
                ).fetchone()[0]
            self.assertEqual(replay_count, 0)

    def test_unknown_inserted_at_checkpoint_blocks_phase_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_advance = Ledger.advance_classroom_replay_phase
            injected = False

            def inject_unknown(
                ledger,
                claim,
                *,
                expected_phase,
                next_phase,
            ):
                nonlocal injected
                if not injected and expected_phase == 1:
                    injected = True
                    intent = OrderIntent(
                        f"{claim.session_id}-1:US:AAPL:BUY:retry-1",
                        Market.US,
                        "AAPL",
                        OrderSide.BUY,
                        OrderType.LIMIT,
                        Decimal("1"),
                        Decimal("180"),
                        "USD",
                        strategy_id=claim.strategy_id,
                    )
                    broker = PaperBroker(ledger)
                    broker.submit_order(intent)
                    broker.mark_unknown(intent.client_order_id)
                return real_advance(
                    ledger,
                    claim,
                    expected_phase=expected_phase,
                    next_phase=next_phase,
                )

            with mock.patch.object(
                Ledger, "advance_classroom_replay_phase", new=inject_unknown
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "UNKNOWN target order"
                ):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT phase,owner_token FROM classroom_replays"
                ).fetchone()
                sells = conn.execute(
                    "SELECT COUNT(*) FROM broker_orders WHERE side='SELL'"
                ).fetchone()[0]
                trades = conn.execute(
                    "SELECT COUNT(*) FROM realized_trades"
                ).fetchone()[0]
            self.assertEqual(replay, (1, None))
            self.assertEqual((sells, trades), (0, 0))

    def test_terminal_predicted_namespace_is_quarantined_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            broker = PaperBroker(ledger)
            strategy_id = "classroom-replay:classroom-000001"
            buy = OrderIntent(
                "classroom-000001-1:KR:005930:BUY",
                Market.KR,
                "005930",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("70000"),
                "KRW",
                strategy_id=strategy_id,
            )
            sell = OrderIntent(
                "classroom-000001-3:KR:005930:SELL",
                Market.KR,
                "005930",
                OrderSide.SELL,
                OrderType.MARKET,
                Decimal("1"),
                None,
                "KRW",
                strategy_id=strategy_id,
                reason="trailing_stop",
            )
            broker.submit_order(buy)
            broker.fill_order(
                buy.client_order_id,
                "foreign-buy",
                Decimal("1"),
                Decimal("70000"),
            )
            broker.submit_order(sell)
            broker.fill_order(
                sell.client_order_id,
                "foreign-sell",
                Decimal("1"),
                Decimal("69000"),
            )
            before = ledger.count_realized_trades(strategy_id)

            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000002")
            self.assertEqual(result["realized_trades"], 2)
            with sqlite3.connect(path) as conn:
                replays = conn.execute(
                    "SELECT session_id,status,abort_reason "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
                foreign = conn.execute(
                    "SELECT client_order_id,status FROM broker_orders "
                    "WHERE strategy_id=? ORDER BY client_order_id",
                    (strategy_id,),
                ).fetchall()
            self.assertEqual(before, 1)
            self.assertEqual(
                replays,
                [
                    ("classroom-000001", "ABORTED", "namespace_collision"),
                    ("classroom-000002", "COMPLETED", None),
                ],
            )
            self.assertEqual(
                foreign,
                [
                    (buy.client_order_id, "FILLED"),
                    (sell.client_order_id, "FILLED"),
                ],
            )

    def test_existing_terminal_noncanonical_history_is_aborted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "setup-owner", lease_seconds=60
            )
            broker = PaperBroker(ledger)
            for market, symbol, price, currency, exit_price in (
                (Market.KR, "005930", "70000", "KRW", "69000"),
                (Market.US, "AAPL", "180", "USD", "175"),
            ):
                buy = OrderIntent(
                    f"spoof:{market.value}:{symbol}:BUY",
                    market,
                    symbol,
                    OrderSide.BUY,
                    OrderType.LIMIT,
                    Decimal("1"),
                    Decimal(price),
                    currency,
                    strategy_id=claim.strategy_id,
                )
                sell = OrderIntent(
                    f"spoof:{market.value}:{symbol}:SELL",
                    market,
                    symbol,
                    OrderSide.SELL,
                    OrderType.MARKET,
                    Decimal("1"),
                    None,
                    currency,
                    strategy_id=claim.strategy_id,
                    reason="trailing_stop",
                )
                broker.submit_order(buy)
                broker.fill_order(
                    buy.client_order_id,
                    f"spoof-{symbol}-buy",
                    Decimal("1"),
                    Decimal(price),
                )
                broker.submit_order(sell)
                broker.fill_order(
                    sell.client_order_id,
                    f"spoof-{symbol}-sell",
                    Decimal("1"),
                    Decimal(exit_price),
                )
            ledger.release_classroom_replay(claim)

            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000002")
            with sqlite3.connect(path) as conn:
                replays = conn.execute(
                    "SELECT session_id,status,abort_reason "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
                spoof_orders = conn.execute(
                    "SELECT COUNT(*) FROM broker_orders "
                    "WHERE strategy_id=? AND client_order_id LIKE 'spoof:%'",
                    (claim.strategy_id,),
                ).fetchone()[0]
            self.assertEqual(
                replays,
                [
                    (
                        "classroom-000001",
                        "ABORTED",
                        "noncanonical_order_history",
                    ),
                    ("classroom-000002", "COMPLETED", None),
                ],
            )
            self.assertEqual(spoof_orders, 4)

    def test_retry_chain_requires_contiguous_terminal_predecessors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "setup-owner", lease_seconds=60
            )
            forged = OrderIntent(
                "classroom-000001-1:US:AAPL:BUY:retry-999",
                Market.US,
                "AAPL",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("180"),
                "USD",
                strategy_id=claim.strategy_id,
            )
            PaperBroker(ledger).submit_order(forged)
            ledger.release_classroom_replay(claim)

            with self.assertRaisesRegex(RuntimeError, "successor lineage"):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT phase,owner_token FROM classroom_replays"
                ).fetchone()
                order = conn.execute(
                    "SELECT status FROM broker_orders WHERE client_order_id=?",
                    (forged.client_order_id,),
                ).fetchone()
            self.assertEqual(replay, (1, None))
            self.assertEqual(order, ("ACCEPTED",))

    def test_retry_chain_rejects_two_simultaneous_active_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            claim = ledger.claim_classroom_replay(
                "setup-owner", lease_seconds=60
            )
            broker = PaperBroker(ledger)
            base = "classroom-000001-1:US:AAPL:BUY"
            for client_order_id in (base, f"{base}:retry-1"):
                broker.submit_order(
                    OrderIntent(
                        client_order_id,
                        Market.US,
                        "AAPL",
                        OrderSide.BUY,
                        OrderType.LIMIT,
                        Decimal("1"),
                        Decimal("180"),
                        "USD",
                        strategy_id=claim.strategy_id,
                    )
                )
            ledger.release_classroom_replay(claim)

            with self.assertRaisesRegex(RuntimeError, "successor lineage"):
                run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT phase,owner_token FROM classroom_replays"
                ).fetchone()
                statuses = conn.execute(
                    "SELECT status FROM broker_orders "
                    "WHERE client_order_id IN (?,?) ORDER BY client_order_id",
                    (base, f"{base}:retry-1"),
                ).fetchall()
            self.assertEqual(replay, (1, None))
            self.assertEqual(statuses, [("ACCEPTED",), ("ACCEPTED",)])

    def test_unknown_inserted_at_completion_prevents_certification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_complete = Ledger.complete_classroom_replay
            unknown_id = "foreign:US:AAPL:BUY:completion-race"
            injected = False

            def inject_unknown(ledger, claim, *, expected_trades):
                nonlocal injected
                if not injected:
                    injected = True
                    broker = PaperBroker(ledger)
                    intent = OrderIntent(
                        unknown_id,
                        Market.US,
                        "AAPL",
                        OrderSide.BUY,
                        OrderType.LIMIT,
                        Decimal("1"),
                        Decimal("180"),
                        "USD",
                        strategy_id="foreign_strategy",
                    )
                    broker.submit_order(intent)
                    broker.mark_unknown(unknown_id)
                return real_complete(
                    ledger, claim, expected_trades=expected_trades
                )

            with mock.patch.object(
                Ledger, "complete_classroom_replay", new=inject_unknown
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "UNKNOWN target order"
                ):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,owner_token FROM classroom_replays"
                ).fetchone()
                trades = conn.execute(
                    "SELECT COUNT(*) FROM realized_trades"
                ).fetchone()[0]
            self.assertEqual(replay, ("INCOMPLETE", 4, None))
            self.assertEqual(trades, 2)

            ledger = Ledger(path)
            ledger.transition_order(unknown_id, OrderStatus.CANCELED)
            result = run_classroom_replay(path)
            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)

    def test_completion_rejects_missing_closing_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_complete = Ledger.complete_classroom_replay
            stripped = False

            def strip_closing_provenance(
                ledger,
                claim,
                *,
                expected_trades,
            ):
                nonlocal stripped
                if not stripped:
                    stripped = True
                    with sqlite3.connect(path) as conn:
                        conn.execute(
                            "UPDATE realized_trades SET "
                            "exit_client_order_id=NULL,exit_fill_id=NULL "
                            "WHERE strategy_id=? AND market='KR'",
                            (claim.strategy_id,),
                        )
                return real_complete(
                    ledger,
                    claim,
                    expected_trades=expected_trades,
                )

            with mock.patch.object(
                Ledger,
                "complete_classroom_replay",
                new=strip_closing_provenance,
            ):
                with self.assertRaisesRegex(RuntimeError, "provenance"):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,owner_token FROM classroom_replays"
                ).fetchone()
            self.assertEqual(replay, ("INCOMPLETE", 4, None))

    def test_foreign_session_exit_cannot_fill_or_certify_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            real_advance = Ledger.advance_classroom_replay_phase
            foreign_id = "classroom-000001-3:KR:005930:SELL"
            injected = False

            def inject_foreign_exit(
                ledger,
                claim,
                *,
                expected_phase,
                next_phase,
            ):
                nonlocal injected
                advanced = real_advance(
                    ledger,
                    claim,
                    expected_phase=expected_phase,
                    next_phase=next_phase,
                )
                if not injected and expected_phase == 2:
                    injected = True
                    PaperBroker(ledger).submit_order(
                        OrderIntent(
                            foreign_id,
                            Market.KR,
                            "005930",
                            OrderSide.SELL,
                            OrderType.MARKET,
                            Decimal("1"),
                            None,
                            "KRW",
                            strategy_id="foreign_strategy",
                            reason="foreign_exit",
                        )
                    )
                return advanced

            with mock.patch.object(
                Ledger,
                "advance_classroom_replay_phase",
                new=inject_foreign_exit,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "foreign_exit_strategy"
                ):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                replay = conn.execute(
                    "SELECT status,phase,owner_token FROM classroom_replays"
                ).fetchone()
                foreign = conn.execute(
                    "SELECT status,filled_quantity,strategy_id "
                    "FROM broker_orders WHERE client_order_id=?",
                    (foreign_id,),
                ).fetchone()
                foreign_fills = conn.execute(
                    "SELECT COUNT(*) FROM fills WHERE client_order_id=?",
                    (foreign_id,),
                ).fetchone()[0]
                trades = conn.execute(
                    "SELECT COUNT(*) FROM realized_trades"
                ).fetchone()[0]
            self.assertEqual(replay, ("INCOMPLETE", 3, None))
            self.assertEqual(foreign, ("ACCEPTED", "0", "foreign_strategy"))
            self.assertEqual((foreign_fills, trades), (0, 1))

            Ledger(path).transition_order(foreign_id, OrderStatus.CANCELED)
            result = run_classroom_replay(path)

            self.assertEqual(result["session"], "classroom-000001")
            self.assertEqual(result["realized_trades"], 2)
            with sqlite3.connect(path) as conn:
                exits = conn.execute(
                    "SELECT client_order_id,status,strategy_id "
                    "FROM broker_orders WHERE market='KR' AND side='SELL' "
                    "ORDER BY client_order_id"
                ).fetchall()
            self.assertEqual(
                exits,
                [
                    (foreign_id, "CANCELED", "foreign_strategy"),
                    (
                        f"{foreign_id}:retry-1",
                        "FILLED",
                        "classroom-replay:classroom-000001",
                    ),
                ],
            )

    def test_namespace_collision_position_is_never_auto_settled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            ledger = Ledger(path)
            broker = PaperBroker(ledger)
            strategy_id = "classroom-replay:classroom-000001"
            buy = OrderIntent(
                "classroom-000001-1:KR:005930:BUY",
                Market.KR,
                "005930",
                OrderSide.BUY,
                OrderType.LIMIT,
                Decimal("1"),
                Decimal("70000"),
                "KRW",
                strategy_id=strategy_id,
            )
            broker.submit_order(buy)
            broker.fill_order(
                buy.client_order_id,
                "foreign-buy",
                Decimal("1"),
                Decimal("70000"),
            )
            ledger.update_high_water(Market.KR, "005930", Decimal("76000"))

            for _ in range(2):
                with self.assertRaisesRegex(
                    RuntimeError, "unrelated position"
                ):
                    run_classroom_replay(path)

            with sqlite3.connect(path) as conn:
                position = conn.execute(
                    "SELECT quantity,strategy_id FROM positions "
                    "WHERE market='KR' AND symbol='005930'"
                ).fetchone()
                collision_writes = conn.execute(
                    "SELECT COUNT(*) FROM broker_orders "
                    "WHERE strategy_id=? AND side='SELL'",
                    (strategy_id,),
                ).fetchone()[0]
                collision_fills = conn.execute(
                    "SELECT COUNT(*) FROM fills "
                    "JOIN broker_orders USING(client_order_id) "
                    "WHERE broker_orders.strategy_id=? "
                    "AND broker_orders.side='SELL'",
                    (strategy_id,),
                ).fetchone()[0]
                collision_trades = conn.execute(
                    "SELECT COUNT(*) FROM realized_trades "
                    "WHERE strategy_id=?",
                    (strategy_id,),
                ).fetchone()[0]
                replays = conn.execute(
                    "SELECT session_id,status,abort_reason "
                    "FROM classroom_replays ORDER BY sequence"
                ).fetchall()
            self.assertEqual(position, ("1", strategy_id))
            self.assertEqual(
                (collision_writes, collision_fills, collision_trades),
                (0, 0, 0),
            )
            self.assertEqual(
                replays,
                [
                    ("classroom-000001", "ABORTED", "namespace_collision"),
                    ("classroom-000002", "INCOMPLETE", None),
                ],
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
