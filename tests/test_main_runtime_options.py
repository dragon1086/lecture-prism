import os
import unittest
from argparse import Namespace

import main


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


if __name__ == "__main__":
    unittest.main()
