import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest import mock

import main
import runtime_config
import screening
from prism_core.market_data import MarketDataUnavailable


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_TRADE_MODE",
    "LECTURE_SCREENING_MODE",
    "LECTURE_LLM_MODE",
    "LECTURE_REPORT_MODE",
    "LECTURE_RESEARCH_TOOLS",
    "LECTURE_BROKER",
    "LECTURE_BROKER_MODE",
    "LECTURE_ENABLE_LIVE_BROKER",
    "LECTURE_ALLOW_REAL_BROKER",
    "LECTURE_UNATTENDED_LIVE_ACK",
    "LECTURE_NOTIFY_DISCORD",
    "LECTURE_REPORT_CHANNEL",
    "DISCORD_WEBHOOK_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PRISM_OPENAI_AUTH_MODE",
    "PERPLEXITY_API_KEY",
    "FIRECRAWL_API_KEY",
}


class _NoopNotifier:
    async def screening(self, *args, **kwargs):
        return False

    async def analysis(self, *args, **kwargs):
        return False

    async def trading(self, *args, **kwargs):
        return False

    async def summary(self, *args, **kwargs):
        return False

    async def feedback(self, *args, **kwargs):
        return False


class MainRuntimeOptionsTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._patches = [
            mock.patch.object(runtime_config, "load_dotenv_once"),
            mock.patch("brokers.factory.load_dotenv_once"),
            mock.patch("notifications.load_dotenv_once"),
            mock.patch("notifications.build_notifier", return_value=_NoopNotifier()),
        ]
        (
            self.runtime_load_dotenv_once,
            self.broker_load_dotenv_once,
            self.notification_load_dotenv_once,
            self.build_notifier,
        ) = [patcher.start() for patcher in self._patches]

    def tearDown(self):
        for patcher in reversed(self._patches):
            patcher.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_env_paper_profile_uses_broker_path_by_default(self):
        os.environ["LECTURE_PROFILE"] = "paper"

        opts = main._resolve_runtime_options(Namespace(live=False, dry_run=False, real=False))

        self.assertFalse(opts["dry_run"])
        self.assertTrue(opts["use_real_data"])
        self.assertEqual(opts["config"].trade_mode, "demo")

    def test_operating_profiles_explicitly_select_detailed_screening_source(self):
        expected = {
            "classroom": ("fixture", "mock"),
            "backtest": ("fixture", "mock"),
            "paper": ("real", "yfinance"),
            "live": ("real", "yfinance"),
        }
        for profile, (screening_mode, data_mode) in expected.items():
            with self.subTest(profile=profile):
                config = runtime_config.load_runtime_config(profile)
                self.assertEqual(config.screening_mode, screening_mode)
                self.assertEqual(config.data_mode, data_mode)

    def test_paper_and_live_cannot_be_overridden_to_mock_screening(self):
        with mock.patch.dict(
            os.environ,
            {"LECTURE_DATA_MODE": "mock", "LECTURE_SCREENING_MODE": "mock"},
        ):
            for profile in ("paper", "live"):
                with self.subTest(profile=profile):
                    config = runtime_config.load_runtime_config(profile)
                    self.assertEqual(config.screening_mode, "real")
                    self.assertEqual(config.data_mode, "yfinance")

    def test_target_ticker_infers_market_by_shape_and_uses_shared_validation(self):
        for symbol in ("005930", "AAPL"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    asyncio.run(screening.run_screening(target_ticker=symbol)),
                    [symbol],
                )
        for invalid in ("5930", "aapl", "005930.KS", " AAPL"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    asyncio.run(screening.run_screening(target_ticker=invalid))

    def test_legacy_mock_screening_still_returns_symbol_strings(self):
        symbols = asyncio.run(screening.run_screening(use_real=False))
        self.assertTrue(symbols)
        self.assertTrue(all(isinstance(symbol, str) for symbol in symbols))

    def test_paper_detailed_screening_failure_never_uses_demo_fallback(self):
        config = runtime_config.load_runtime_config("paper")
        failure = MarketDataUnavailable("stale market snapshot")
        with runtime_config.runtime_config_scope(config), mock.patch.object(
            screening,
            "run_detailed_screening",
            new=mock.AsyncMock(side_effect=failure),
            create=True,
        ) as detailed, mock.patch.object(
            screening,
            "_filter_candidates",
            new=mock.AsyncMock(side_effect=AssertionError("legacy fallback")),
        ):
            with self.assertRaises(MarketDataUnavailable):
                asyncio.run(screening.run_screening(use_real=True))

        detailed.assert_awaited_once()

    def test_paper_detailed_screening_adapts_candidates_to_legacy_symbols(self):
        config = runtime_config.load_runtime_config("paper")
        detailed_candidates = [
            SimpleNamespace(instrument=SimpleNamespace(symbol="AAPL"))
        ]
        with runtime_config.runtime_config_scope(config), mock.patch.object(
            screening,
            "run_detailed_screening",
            new=mock.AsyncMock(return_value=detailed_candidates),
            create=True,
        ):
            result = asyncio.run(screening.run_screening(use_real=True))

        self.assertEqual(result, ["AAPL"])

    def test_all_detailed_profiles_route_through_candidate_facade(self):
        detailed_candidates = [
            SimpleNamespace(instrument=SimpleNamespace(symbol="AAPL"))
        ]
        for profile in ("classroom", "backtest", "paper", "live"):
            with self.subTest(profile=profile):
                config = runtime_config.load_runtime_config(profile)
                with runtime_config.runtime_config_scope(config), mock.patch.object(
                    screening,
                    "run_detailed_screening",
                    new=mock.AsyncMock(return_value=detailed_candidates),
                ) as detailed:
                    result = asyncio.run(screening.run_screening())

                self.assertEqual(result, ["AAPL"])
                detailed.assert_awaited_once_with(
                    profile=profile,
                    target_ticker=None,
                )

    def test_paper_target_ticker_filters_detailed_path_without_bypassing_it(self):
        config = runtime_config.load_runtime_config("paper")
        detailed_candidates = [
            SimpleNamespace(instrument=SimpleNamespace(symbol="AAPL"))
        ]
        with runtime_config.runtime_config_scope(config), mock.patch.object(
            screening,
            "run_detailed_screening",
            new=mock.AsyncMock(return_value=detailed_candidates),
        ) as detailed:
            result = asyncio.run(
                screening.run_screening(target_ticker="AAPL", use_real=True)
            )

        self.assertEqual(result, ["AAPL"])
        detailed.assert_awaited_once_with(profile="paper", target_ticker="AAPL")

    def test_cli_dry_run_overrides_env_trade_mode(self):
        os.environ["LECTURE_TRADE_MODE"] = "real"

        opts = main._resolve_runtime_options(Namespace(live=False, dry_run=True, real=False))

        self.assertTrue(opts["dry_run"])

    def test_screening_mode_real_enables_real_screening(self):
        os.environ["LECTURE_SCREENING_MODE"] = "real"

        opts = main._resolve_runtime_options(Namespace(live=False, dry_run=False, real=False))

        self.assertTrue(opts["use_real_data"])

    def test_cli_profile_alias_selects_classroom_safely(self):
        opts = main._resolve_runtime_options(
            Namespace(
                profile="replay",
                live=True,
                dry_run=False,
                real=True,
            )
        )

        self.assertEqual(opts["config"].profile, "classroom")
        self.assertTrue(opts["dry_run"])
        self.assertFalse(opts["use_real_data"])

    def test_parser_accepts_new_profiles_and_aliases(self):
        parser = main._build_arg_parser()

        for profile in ("classroom", "replay", "backtest", "walk_forward"):
            with self.subTest(profile=profile):
                self.assertEqual(
                    parser.parse_args(["--profile", profile]).profile,
                    profile,
                )

    def test_run_pipeline_branches_only_for_classroom_and_returns_summary(self):
        summary = {
            "cycles": 3,
            "final_positions": 0,
            "realized_trades": 2,
            "markets": ["KR", "US"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classroom.db"
            with mock.patch("db.DB_PATH", path), mock.patch(
                "prism_core.classroom.run_classroom_replay",
                return_value=summary,
            ) as replay:
                result = asyncio.run(
                    main.run_pipeline(
                        config=runtime_config.load_runtime_config("classroom")
                    )
                )

        self.assertEqual(result, summary)
        replay.assert_called_once_with(path)

    def test_backtest_profile_keeps_existing_pipeline_branch(self):
        with mock.patch(
            "screening.run_screening", new=mock.AsyncMock(return_value=[])
        ), mock.patch(
            "prism_core.classroom.run_classroom_replay"
        ) as replay:
            result = asyncio.run(
                main.run_pipeline(
                    config=runtime_config.load_runtime_config("backtest")
                )
            )

        self.assertIsNone(result)
        replay.assert_not_called()

    def test_pipeline_tests_do_not_reach_ambient_notification_side_effects(self):
        with mock.patch(
            "notifications.load_dotenv_once",
            side_effect=AssertionError("ambient .env loader"),
        ), mock.patch(
            "notifications.urlopen",
            side_effect=AssertionError("network notification"),
        ), mock.patch(
            "screening.run_screening", new=mock.AsyncMock(return_value=[])
        ):
            result = asyncio.run(
                main.run_pipeline(config=runtime_config.load_runtime_config("mock"))
            )

        self.assertIsNone(result)
        self.build_notifier.assert_called_once_with()

    def test_direct_backtest_pipeline_cannot_enable_real_data_or_broker_path(self):
        analysis = {
            "ticker": "005930",
            "recommendation": "PASS",
            "decision": "관망",
            "buy_score": 0,
            "target_price": 0,
        }
        with mock.patch(
            "screening.run_screening",
            new=mock.AsyncMock(return_value=["005930"]),
        ) as screening, mock.patch(
            "analysis.run_analysis_report",
            new=mock.AsyncMock(return_value={"ticker": "005930", "current_price": 1}),
        ), mock.patch(
            "buy_agent.run_buy_agent", new=mock.AsyncMock(return_value=analysis)
        ), mock.patch(
            "report_writer.write_reports", return_value=[]
        ), mock.patch(
            "trading.run_trading", new=mock.AsyncMock(return_value=[])
        ) as trading, mock.patch(
            "feedback.run_feedback", new=mock.AsyncMock()
        ):
            asyncio.run(
                main.run_pipeline(
                    dry_run=False,
                    use_real_data=True,
                    config=runtime_config.load_runtime_config("backtest"),
                )
            )

        self.assertFalse(screening.await_args.kwargs["use_real"])
        self.assertTrue(trading.await_args.kwargs["dry_run"])

    def test_explicit_backtest_config_reaches_real_downstream_readers(self):
        hostile = {
            "LECTURE_PROFILE": "live",
            "LECTURE_DATA_MODE": "yfinance",
            "LECTURE_LLM_MODE": "openai",
            "LECTURE_REPORT_MODE": "research",
            "LECTURE_RESEARCH_TOOLS": "perplexity,firecrawl",
            "LECTURE_TRADE_MODE": "real",
            "OPENAI_API_KEY": "must-not-be-used",
            "PRISM_OPENAI_AUTH_MODE": "chatgpt_oauth",
            "PERPLEXITY_API_KEY": "must-not-be-used",
            "FIRECRAWL_API_KEY": "must-not-be-used",
        }
        cfg = runtime_config.load_runtime_config("backtest")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest.db"
            with mock.patch.dict(os.environ, hostile, clear=False), mock.patch(
                "db.DB_PATH", path
            ), mock.patch(
                "data_source._fetch_real",
                side_effect=AssertionError("real data path"),
            ), mock.patch(
                "analysis._llm_complete",
                new=mock.AsyncMock(side_effect=AssertionError("LLM path")),
            ), mock.patch(
                "research_tools.build_research_context",
                side_effect=AssertionError("research path"),
            ), mock.patch(
                "cores.chatgpt_proxy.start_proxy",
                new=mock.AsyncMock(side_effect=AssertionError("OAuth path")),
            ), mock.patch(
                "report_writer.write_reports", return_value=[]
            ):
                result = asyncio.run(
                    main.run_pipeline(
                        target_ticker="005930",
                        config=cfg,
                    )
                )
                downstream = runtime_config.load_runtime_config()

        self.assertIsNone(result)
        self.assertEqual(downstream.profile, "live")


if __name__ == "__main__":
    unittest.main()
