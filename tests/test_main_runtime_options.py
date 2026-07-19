import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
from unittest import mock

import main
import runtime_config


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_TRADE_MODE",
    "LECTURE_SCREENING_MODE",
}


class MainRuntimeOptionsTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_env_paper_profile_uses_broker_path_by_default(self):
        os.environ["LECTURE_PROFILE"] = "paper"

        opts = main._resolve_runtime_options(Namespace(live=False, dry_run=False, real=False))

        self.assertFalse(opts["dry_run"])
        self.assertFalse(opts["use_real_data"])
        self.assertEqual(opts["config"].trade_mode, "demo")

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
            ) as replay, mock.patch.object(
                main,
                "_maybe_start_chatgpt_oauth_proxy",
                new=mock.AsyncMock(side_effect=AssertionError("OAuth path")),
            ):
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
        ), mock.patch.object(
            main,
            "_maybe_start_chatgpt_oauth_proxy",
            new=mock.AsyncMock(return_value=(False, {})),
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
            "analysis.run_analysis", new=mock.AsyncMock(return_value=analysis)
        ), mock.patch(
            "report_writer.write_reports", return_value=[]
        ), mock.patch(
            "trading.run_trading", new=mock.AsyncMock(return_value=[])
        ) as trading, mock.patch(
            "feedback.run_feedback", new=mock.AsyncMock()
        ), mock.patch.object(
            main,
            "_maybe_start_chatgpt_oauth_proxy",
            new=mock.AsyncMock(return_value=(False, {})),
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
