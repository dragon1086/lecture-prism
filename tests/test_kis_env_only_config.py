from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TRADING_DIR = ROOT / "trading" / "trading"
KIS_AUTH_PATH = TRADING_DIR / "kis_auth.py"
DOMESTIC_TRADING_PATH = TRADING_DIR / "domestic_stock_trading.py"


def load_fresh_kis_auth():
    sys.modules.pop("kis_auth", None)
    spec = importlib.util.spec_from_file_location("kis_auth", KIS_AUTH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load kis_auth")
    module = importlib.util.module_from_spec(spec)
    sys.modules["kis_auth"] = module
    spec.loader.exec_module(module)
    return module


def load_fresh_domestic_stock_trading():
    sys.modules.pop("domestic_stock_trading", None)
    sys.modules.pop("kis_auth", None)
    spec = importlib.util.spec_from_file_location(
        "domestic_stock_trading", DOMESTIC_TRADING_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load domestic_stock_trading")
    module = importlib.util.module_from_spec(spec)
    sys.modules["domestic_stock_trading"] = module
    spec.loader.exec_module(module)
    return module


class KISEnvOnlyConfigTest(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("kis_auth", None)
        sys.modules.pop("domestic_stock_trading", None)

    def test_kis_auth_imports_without_yaml_and_resolves_env_accounts(self):
        config_file = TRADING_DIR / "config" / "kis_devlp.yaml"
        self.assertFalse(config_file.exists())

        env = {
            "LECTURE_KIS_MODE": "demo",
            "KIS_PAPER_APP_KEY": "PSVT-paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "12345678",
            "KIS_PAPER_PRODUCT_CODE": "01",
            "KIS_REAL_APP_KEY": "PS-real-key",
            "KIS_REAL_APP_SECRET": "real-secret",
            "KIS_REAL_ACCOUNT_NO": "87654321",
            "KIS_REAL_PRODUCT_CODE": "01",
            "KIS_HTS_ID": "student-hts",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "brokers.config.load_env_file", return_value=None
        ) as load_env:
            module = load_fresh_kis_auth()

        self.assertEqual(module.get_config()["default_mode"], "demo")
        self.assertEqual(module.DEFAULT_PRODUCT_CODE, "01")
        paper = module.resolve_account(svr="vps", product="01")
        real = module.resolve_account(svr="prod", product="01")
        self.assertEqual((paper["svr"], paper["account"], paper["product"]), ("vps", "12345678", "01"))
        self.assertEqual((real["svr"], real["account"], real["product"]), ("prod", "87654321", "01"))
        load_env.assert_called_once_with(ROOT / ".env")

    def test_kis_auth_env_loader_does_not_depend_on_current_working_directory(self):
        env = {
            "KIS_PAPER_APP_KEY": "PSVT-paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "12345678",
        }
        original_cwd = Path.cwd()
        with patch.dict(os.environ, env, clear=True), patch(
            "brokers.config.load_env_file", return_value=None
        ) as load_env:
            os.chdir(Path(os.environ.get("TMPDIR", "/tmp")))
            try:
                module = load_fresh_kis_auth()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(module.resolve_account(svr="vps")["account"], "12345678")
        load_env.assert_called_once_with(ROOT / ".env")

    def test_selected_kis_mode_ignores_deleted_yaml_config_path(self):
        from brokers.kis import selected_kis_mode

        with patch.dict(os.environ, {}, clear=True):
            mode = selected_kis_mode(config_path=TRADING_DIR / "config" / "kis_devlp.yaml")

        self.assertEqual(mode, "demo")

    def test_domestic_trading_module_imports_without_yaml(self):
        env = {
            "LECTURE_KIS_MODE": "demo",
            "KIS_PAPER_APP_KEY": "PSVT-paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "12345678",
            "KIS_PAPER_PRODUCT_CODE": "01",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "brokers.config.load_env_file", return_value=None
        ):
            module = load_fresh_domestic_stock_trading()

        self.assertEqual(module.DomesticStockTrading.DEFAULT_MODE, "demo")
        self.assertEqual(module.DomesticStockTrading.DEFAULT_BUY_AMOUNT, 10000)


if __name__ == "__main__":
    unittest.main()
