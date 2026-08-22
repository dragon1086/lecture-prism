import os
import unittest
from unittest import mock

import runtime_config


_ENV_KEYS = {
    "LECTURE_PROFILE",
    "LECTURE_DATA_MODE",
    "LECTURE_SUPPLY_SOURCE",
    "LECTURE_SCREENING_MODE",
    "LECTURE_LLM_MODE",
    "LECTURE_REPORT_MODE",
    "LECTURE_RESEARCH_TOOLS",
    "LECTURE_TRADE_MODE",
    "LECTURE_BROKER",
    "LECTURE_BROKER_MODE",
    "LECTURE_ENABLE_LIVE_BROKER",
    "LECTURE_ALLOW_REAL_BROKER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PRISM_OPENAI_AUTH_MODE",
    "FIRECRAWL_API_KEY",
    "PERPLEXITY_API_KEY",
}


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._load_env_patch = mock.patch.object(runtime_config, "load_dotenv_once")
        self.load_dotenv_once = self._load_env_patch.start()

    def tearDown(self):
        self._load_env_patch.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_load_runtime_config_uses_explicit_loader_boundary_under_unittest(self):
        runtime_config.load_runtime_config("mock")

        self.load_dotenv_once.assert_called_once_with()

    def test_default_profile_is_mock_and_simulation_safe(self):
        cfg = runtime_config.load_runtime_config()

        self.assertEqual(cfg.profile, "mock")
        self.assertEqual(cfg.data_mode, "mock")
        self.assertEqual(cfg.supply_source, "proxy")
        self.assertEqual(cfg.screening_mode, "mock")
        self.assertEqual(cfg.llm_mode, "mock")
        self.assertEqual(cfg.report_mode, "lite")
        self.assertEqual(cfg.trade_mode, "simulation")
        self.assertTrue(runtime_config.resolve_trade_dry_run(False, False, cfg))

    def test_research_profile_enables_tools_without_enabling_broker_orders(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["FIRECRAWL_API_KEY"] = "fc-test"
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"

        cfg = runtime_config.load_runtime_config()

        self.assertEqual(cfg.profile, "research")
        self.assertEqual(cfg.data_mode, "auto")
        self.assertEqual(cfg.report_mode, "research")
        self.assertEqual(cfg.trade_mode, "simulation")
        self.assertEqual(cfg.research_tools, ("perplexity", "firecrawl"))
        self.assertTrue(cfg.tool_ready["perplexity"])
        self.assertTrue(cfg.tool_ready["firecrawl"])
        self.assertTrue(runtime_config.resolve_trade_dry_run(False, False, cfg))

    def test_paper_trade_mode_uses_broker_path_but_cli_dry_run_wins(self):
        os.environ["LECTURE_PROFILE"] = "paper"

        cfg = runtime_config.load_runtime_config()

        self.assertEqual(cfg.trade_mode, "demo")
        self.assertFalse(runtime_config.resolve_trade_dry_run(False, False, cfg))
        self.assertTrue(runtime_config.resolve_trade_dry_run(False, True, cfg))
        self.assertFalse(runtime_config.resolve_trade_dry_run(True, False, cfg))

    def test_explicit_env_values_override_profile_defaults(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["LECTURE_DATA_MODE"] = "mock"
        os.environ["LECTURE_REPORT_MODE"] = "lite"
        os.environ["LECTURE_RESEARCH_TOOLS"] = "perplexity"

        cfg = runtime_config.load_runtime_config()

        self.assertEqual(cfg.data_mode, "mock")
        self.assertEqual(cfg.report_mode, "lite")
        self.assertEqual(cfg.research_tools, ("perplexity",))

    def test_kis_supply_source_is_explicit_and_visible_in_summary(self):
        os.environ["LECTURE_PROFILE"] = "real_data"
        os.environ["LECTURE_SUPPLY_SOURCE"] = "kis"

        cfg = runtime_config.load_runtime_config()

        self.assertEqual(cfg.supply_source, "kis")
        self.assertIn("supply=kis", cfg.summary())

    def test_openai_base_url_alone_does_not_enable_private_oauth_proxy(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["OPENAI_BASE_URL"] = "http://localhost:18741/v1"

        cfg = runtime_config.load_runtime_config()

        self.assertFalse(cfg.llm_enabled)
        self.assertFalse(cfg.chatgpt_oauth_requested)

    def test_explicit_oauth_mode_needs_no_api_key(self):
        os.environ["LECTURE_PROFILE"] = "research"
        os.environ["LECTURE_LLM_MODE"] = "oauth"

        cfg = runtime_config.load_runtime_config()

        self.assertTrue(cfg.llm_enabled)
        self.assertTrue(cfg.chatgpt_oauth_requested)


if __name__ == "__main__":
    unittest.main()
