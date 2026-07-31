import asyncio
from pathlib import Path
import unittest

import analysis


class PipelineSimplificationTest(unittest.TestCase):
    def test_analysis_returns_direct_fields_without_intermediate_trade_plan(self):
        result = asyncio.run(analysis.run_analysis("005930"))

        self.assertNotIn("trade_plan", result)
        for key in (
            "buy_score",
            "current_price",
            "target_price",
            "stop_loss",
            "risk_reward_ratio",
        ):
            self.assertIn(key, result)

    def test_runtime_lecture_adapter_is_removed(self):
        self.assertFalse(Path("cores/lecture_adapter.py").exists())


if __name__ == "__main__":
    unittest.main()
