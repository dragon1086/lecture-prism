from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from prism_core.domain import (
    Candidate,
    EntryContext,
    Instrument,
    Market,
    Regime,
    TriggerType,
)
from prism_core.ledger import Ledger
from prism_core.policy import policy_for
from prism_core.regime import PulseState, RegimeResult


AS_OF = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)


def regime_result(
    regime: Regime = Regime.SIDEWAYS, market: Market = Market.US
) -> RegimeResult:
    return RegimeResult(
        market=market,
        as_of=AS_OF,
        regime=regime,
        confidence=Decimal("0.75"),
        pulse=PulseState.UNDER_PRESSURE,
        metrics={"return_pct": Decimal("1.25"), "distribution_days": 4},
        reasons=("fixture regime",),
        source="fixture",
    )


def candidate(symbol="AAPL", market=Market.US, **overrides) -> Candidate:
    is_kr = market is Market.KR
    names = {
        "005930": "Samsung Electronics",
        "AAPL": "Apple",
        "MSFT": "Microsoft",
    }
    values = {
        "instrument": Instrument(
            symbol=symbol,
            market=market,
            exchange="XKRX" if is_kr else "XNAS",
            currency="KRW" if is_kr else "USD",
            name=names.get(symbol, symbol),
            sector="Technology",
            lot_size=Decimal("1"),
            price_precision=0 if is_kr else 2,
        ),
        "as_of": AS_OF,
        "trigger_type": TriggerType.BREAKOUT,
        "regime": Regime.MODERATE_BULL,
        "feature_values": {"setup": "cup", "volume_ratio": Decimal("2.5")},
        "component_scores": {"trend": Decimal("4"), "volume": Decimal("3")},
        "final_score": Decimal("7"),
        "reference_price": Decimal("100") if is_kr else Decimal("100.00"),
        "stop_price": Decimal("95") if is_kr else Decimal("95.00"),
        "target_price": Decimal("110") if is_kr else Decimal("110.00"),
        "risk_reward_ratio": Decimal("2"),
        "source": "fixture",
    }
    values.update(overrides)
    return Candidate(**values)


def entry_context(selected=None, run_id="run-1", **overrides) -> EntryContext:
    selected = candidate() if selected is None else selected
    values = {
        "client_order_id": (
            f"{run_id}:{selected.instrument.market.value}:"
            f"{selected.instrument.symbol}:BUY"
        ),
        "run_id": run_id,
        "candidate": selected,
        "strategy_id": selected.source,
        "policy": policy_for(selected.regime),
    }
    values.update(overrides)
    return EntryContext(**values)


class MarketProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.ledger = Ledger(Path(self.temporary_directory.name) / "ledger.db")

    def test_market_regime_round_trip_retry_and_collision(self):
        original = regime_result()
        self.ledger.record_market_regime("run-1", original)
        self.ledger.record_market_regime("run-1", original)

        self.assertEqual(
            self.ledger.get_market_regime("run-1", Market.US),
            original,
        )
        with self.assertRaisesRegex(ValueError, "market regime collision"):
            self.ledger.record_market_regime(
                "run-1", regime_result(Regime.STRONG_BULL)
            )
        self.assertEqual(
            self.ledger.get_market_regime("run-1", Market.US),
            original,
        )

    def test_market_regime_uses_canonical_json_and_aware_iso_timestamp(self):
        self.ledger.record_market_regime("run-1", regime_result())

        with sqlite3.connect(self.ledger.path) as conn:
            row = conn.execute(
                "SELECT as_of, confidence, metrics_json, reasons_json "
                "FROM market_regimes WHERE run_id='run-1' AND market='US'"
            ).fetchone()

        self.assertEqual(row[0], AS_OF.isoformat())
        self.assertEqual(row[1], "0.75")
        self.assertEqual(
            row[2],
            '{"distribution_days":4,"return_pct":'
            '{"__prism_decimal__":"1.25"}}',
        )
        self.assertEqual(row[3], '["fixture regime"]')
        self.assertEqual(
            json.loads(row[2])["return_pct"],
            {"__prism_decimal__": "1.25"},
        )

    def test_regime_numeric_string_round_trips_and_decimal_retry_collides(self):
        original = RegimeResult(
            market=Market.US,
            as_of=AS_OF,
            regime=Regime.SIDEWAYS,
            confidence=Decimal("0.75"),
            pulse=PulseState.UNDER_PRESSURE,
            metrics={"code": "123"},
            reasons=("fixture",),
            source="fixture",
        )
        decimal_variant = RegimeResult(
            market=Market.US,
            as_of=AS_OF,
            regime=Regime.SIDEWAYS,
            confidence=Decimal("0.75"),
            pulse=PulseState.UNDER_PRESSURE,
            metrics={"code": Decimal("123")},
            reasons=("fixture",),
            source="fixture",
        )
        self.ledger.record_market_regime("typed", original)

        with self.assertRaisesRegex(ValueError, "market regime collision"):
            self.ledger.record_market_regime("typed", decimal_variant)
        self.assertEqual(
            self.ledger.get_market_regime("typed", Market.US), original
        )

    def test_corrupt_market_regime_rows_fail_closed(self):
        corruptions = (
            ("regime", "NOT_A_REGIME"),
            ("metrics_json", "not-json"),
            (
                "metrics_json",
                '{"x":{"__prism_decimal__":"1","extra":true}}',
            ),
            ("metrics_json", '{"x":{"__unknown_tag__":"1"}}'),
            ("confidence", "not-a-decimal"),
            ("as_of", "2026-06-30T15:00:00"),
        )
        for index, (column, value) in enumerate(corruptions):
            run_id = f"run-{index}"
            self.ledger.record_market_regime(run_id, regime_result())
            with sqlite3.connect(self.ledger.path) as conn:
                conn.execute(
                    f'UPDATE market_regimes SET "{column}"=? WHERE run_id=?',
                    (value, run_id),
                )
            with self.subTest(column=column):
                with self.assertRaises(ValueError):
                    self.ledger.get_market_regime(run_id, Market.US)

    def test_candidates_round_trip_in_market_rank_order_and_retry(self):
        candidates = (
            candidate("AAPL"),
            candidate("005930", Market.KR),
            candidate("MSFT", final_score=Decimal("8")),
        )

        self.ledger.record_candidates("run-1", candidates)
        self.ledger.record_candidates("run-1", candidates)

        self.assertEqual(self.ledger.list_candidates("run-1"), list(candidates))
        self.assertEqual(
            self.ledger.list_candidates("run-1", Market.US),
            [candidates[0], candidates[2]],
        )
        with sqlite3.connect(self.ledger.path) as conn:
            rows = conn.execute(
                "SELECT market,symbol,rank,feature_values_json,"
                "component_scores_json FROM candidates "
                "WHERE run_id='run-1' ORDER BY rowid"
            ).fetchall()
        self.assertEqual([row[:3] for row in rows], [
            ("US", "AAPL", 1), ("KR", "005930", 1), ("US", "MSFT", 2)
        ])
        self.assertEqual(
            rows[0][3],
            '{"setup":"cup","volume_ratio":'
            '{"__prism_decimal__":"2.5"}}',
        )
        self.assertEqual(
            rows[0][4],
            '{"trend":{"__prism_decimal__":"4"},'
            '"volume":{"__prism_decimal__":"3"}}',
        )

    def test_candidate_numeric_string_round_trips_and_decimal_retry_collides(self):
        original = candidate(feature_values={"code": "123"})
        decimal_variant = candidate(feature_values={"code": Decimal("123")})
        self.ledger.record_candidates("typed", (original,))

        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates("typed", (decimal_variant,))
        self.assertEqual(self.ledger.list_candidates("typed"), [original])

    def test_candidates_empty_tuple_and_collision_are_non_mutating(self):
        self.ledger.record_candidates("run-1", ())
        self.assertEqual(self.ledger.list_candidates("run-1"), [])
        original = candidate()
        self.ledger.record_candidates("run-1", (original,))

        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates(
                "run-1", (candidate(final_score=Decimal("8")),)
            )
        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates(
                "run-1", (candidate(source="different"),)
            )
        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates(
                "run-1", (candidate(
                    reference_price=Decimal("101.00"),
                    stop_price=Decimal("96.00"),
                    target_price=Decimal("111.00"),
                ),)
            )
        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates("run-1", (candidate("MSFT"),))
        with self.assertRaisesRegex(ValueError, "candidate collision"):
            self.ledger.record_candidates(
                "run-1", (candidate(trigger_type=TriggerType.PULLBACK),)
            )
        self.assertEqual(self.ledger.list_candidates("run-1"), [original])

    def test_corrupt_candidate_rows_fail_closed(self):
        corruptions = (
            ("exchange", ""),
            ("currency", "EUR"),
            ("lot_size", "not-a-decimal"),
            ("price_precision", -1),
            ("feature_values_json", "not-json"),
            (
                "feature_values_json",
                '{"x":{"__prism_decimal__":"1","extra":true}}',
            ),
            (
                "component_scores_json",
                '{"trend":{"__unknown_tag__":"4"}}',
            ),
            ("component_scores_json", '{"trend":"bad"}'),
            ("trigger_type", "not-a-trigger"),
            ("regime", "not-a-regime"),
            ("final_score", "not-a-decimal"),
            ("market", "XX"),
            ("symbol", "aapl"),
            ("stop_price", "101.00"),
        )
        for index, (column, value) in enumerate(corruptions):
            run_id = f"corrupt-{index}"
            self.ledger.record_candidates(run_id, (candidate(),))
            with sqlite3.connect(self.ledger.path) as conn:
                conn.execute(
                    f'UPDATE candidates SET "{column}"=? WHERE run_id=?',
                    (value, run_id),
                )
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "corrupt stored candidate"):
                    self.ledger.list_candidates(run_id)

    def test_entry_context_round_trip_and_retry_preserve_created_at(self):
        selected = candidate()
        context = entry_context(selected)
        self.ledger.record_candidates("run-1", (selected,))

        self.ledger.record_entry_context(context)
        with sqlite3.connect(self.ledger.path) as conn:
            created_at = conn.execute(
                "SELECT created_at FROM entry_contexts WHERE client_order_id=?",
                (context.client_order_id,),
            ).fetchone()[0]
        self.ledger.record_entry_context(context)

        self.assertEqual(self.ledger.get_entry_context(context.client_order_id), context)
        with sqlite3.connect(self.ledger.path) as conn:
            retry_created_at = conn.execute(
                "SELECT created_at FROM entry_contexts WHERE client_order_id=?",
                (context.client_order_id,),
            ).fetchone()[0]
        self.assertEqual(retry_created_at, created_at)

    def test_entry_context_requires_exact_persisted_candidate_and_contract(self):
        selected = candidate()
        self.ledger.record_candidates("run-1", (selected,))
        invalid = (
            entry_context(candidate(final_score=Decimal("8"))),
            entry_context(strategy_id="different"),
            entry_context(client_order_id="wrong"),
            entry_context(policy=policy_for(Regime.SIDEWAYS)),
        )
        for context in invalid:
            with self.subTest(context=context):
                with self.assertRaises(ValueError):
                    self.ledger.record_entry_context(context)
        self.assertIsNone(self.ledger.get_entry_context("run-1:US:AAPL:BUY"))

    def test_entry_context_collision_does_not_overwrite_existing_row(self):
        selected = candidate()
        context = entry_context(selected)
        self.ledger.record_candidates("run-1", (selected,))
        self.ledger.record_entry_context(context)
        with sqlite3.connect(self.ledger.path) as conn:
            conn.execute(
                "UPDATE entry_contexts SET source='corrupt' "
                "WHERE client_order_id=?",
                (context.client_order_id,),
            )

        with self.assertRaisesRegex(ValueError, "entry context collision"):
            self.ledger.record_entry_context(context)
        with sqlite3.connect(self.ledger.path) as conn:
            source = conn.execute(
                "SELECT source FROM entry_contexts WHERE client_order_id=?",
                (context.client_order_id,),
            ).fetchone()[0]
        self.assertEqual(source, "corrupt")

    def test_corrupt_entry_context_rows_fail_closed(self):
        corruptions = (
            ("client_order_id", "wrong"),
            ("run_id", "wrong-run"),
            ("market", "KR"),
            ("symbol", "MSFT"),
            ("strategy_id", "wrong"),
            ("regime", Regime.SIDEWAYS.value),
            ("trigger_type", TriggerType.PULLBACK.value),
            ("stop_price", "94.00"),
            ("target_price", "111.00"),
            ("risk_reward_ratio", "3"),
            ("trailing_pct", "9"),
            ("source", "wrong"),
            ("created_at", "2026-06-30T15:00:00"),
        )
        for index, (column, value) in enumerate(corruptions):
            run_id = f"entry-corrupt-{index}"
            selected = candidate()
            context = EntryContext(
                client_order_id=f"{run_id}:US:AAPL:BUY",
                run_id=run_id,
                candidate=selected,
                strategy_id=selected.source,
                policy=policy_for(selected.regime),
            )
            self.ledger.record_candidates(run_id, (selected,))
            self.ledger.record_entry_context(context)
            lookup_id = value if column == "client_order_id" else context.client_order_id
            with sqlite3.connect(self.ledger.path) as conn:
                conn.execute(
                    f'UPDATE entry_contexts SET "{column}"=? '
                    "WHERE client_order_id=?",
                    (value, context.client_order_id),
                )
            with self.subTest(column=column):
                with self.assertRaisesRegex(
                    ValueError, "corrupt stored entry context"
                ):
                    self.ledger.get_entry_context(lookup_id)

    def test_market_preparation_is_atomic_and_full_retry_is_idempotent(self):
        us = candidate("AAPL")
        kr = candidate("005930", Market.KR)
        regimes = (
            regime_result(Regime.MODERATE_BULL, Market.US),
            regime_result(Regime.MODERATE_BULL, Market.KR),
        )
        candidates = (us, kr)
        contexts = (entry_context(us), entry_context(kr))

        self.ledger.record_market_preparation(
            "run-1", regimes, candidates, contexts
        )
        self.ledger.record_market_preparation(
            "run-1", regimes, candidates, contexts
        )

        self.assertEqual(
            self.ledger.get_market_regime("run-1", Market.US), regimes[0]
        )
        self.assertEqual(self.ledger.list_candidates("run-1"), list(candidates))
        self.assertEqual(
            [self.ledger.get_entry_context(value.client_order_id) for value in contexts],
            list(contexts),
        )

    def test_market_preparation_rolls_back_conflict_at_each_stage(self):
        selected = candidate()
        regime = regime_result(Regime.MODERATE_BULL)
        context = entry_context(selected)

        self.ledger.record_market_regime(
            "run-1", regime_result(Regime.STRONG_BULL)
        )
        with self.assertRaises(ValueError):
            self.ledger.record_market_preparation(
                "run-1", (regime,), (selected,), (context,)
            )
        self.assertEqual(self.ledger.list_candidates("run-1"), [])
        self.assertIsNone(self.ledger.get_entry_context(context.client_order_id))

        selected_2 = candidate(source="seed")
        self.ledger.record_candidates("run-2", (selected_2,))
        conflicting = candidate(source="new")
        context_2 = entry_context(conflicting, "run-2", strategy_id="new")
        with self.assertRaises(ValueError):
            self.ledger.record_market_preparation(
                "run-2", (regime,), (conflicting,), (context_2,)
            )
        self.assertIsNone(self.ledger.get_market_regime("run-2", Market.US))
        self.assertEqual(self.ledger.list_candidates("run-2"), [selected_2])

        selected_3 = candidate()
        context_3 = entry_context(selected_3, "run-3")
        self.ledger.record_candidates("run-3", (selected_3,))
        self.ledger.record_entry_context(context_3)
        with sqlite3.connect(self.ledger.path) as conn:
            conn.execute(
                "UPDATE entry_contexts SET source='corrupt' "
                "WHERE client_order_id=?",
                (context_3.client_order_id,),
            )
        with self.assertRaises(ValueError):
            self.ledger.record_market_preparation(
                "run-3", (regime,), (selected_3,), (context_3,)
            )
        self.assertIsNone(self.ledger.get_market_regime("run-3", Market.US))


if __name__ == "__main__":
    unittest.main()
