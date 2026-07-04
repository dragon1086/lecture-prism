import os
import tempfile
import unittest
from pathlib import Path

import report_writer


class ReportWriterTests(unittest.TestCase):
    def test_write_analysis_report_creates_markdown_file(self):
        result = {
            "ticker": "005930",
            "company_name": "삼성전자",
            "sector": "반도체",
            "recommendation": "BUY",
            "decision": "진입",
            "buy_score": 8,
            "min_score": 6,
            "current_price": 71200,
            "target_price": 81200,
            "stop_loss": 67600,
            "risk_reward_ratio": 2.8,
            "expected_return_pct": 14.0,
            "expected_loss_pct": 5.1,
            "investment_period": "중기",
            "data_source": "mock",
            "runtime_summary": "profile=mock",
            "technical_summary": "기술 요약",
            "supply_summary": "수급 요약",
            "financial_summary": "재무 요약",
            "industry_summary": "산업 요약",
            "news_summary": "뉴스 요약",
            "market_condition": "시장 요약",
            "rationale": "종합 판단",
            "risk": "주요 리스크",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = report_writer.write_analysis_report(result, output_dir=Path(tmp))

            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            self.assertIn("# 삼성전자 (005930) 분석 보고서", text)
            self.assertIn("## 1. 기술적 분석", text)
            self.assertIn("런타임 설정", text)

    def test_write_reports_respects_off_env(self):
        old = os.environ.get("LECTURE_SAVE_REPORTS")
        os.environ["LECTURE_SAVE_REPORTS"] = "0"
        try:
            self.assertEqual(report_writer.write_reports([{"ticker": "005930"}]), [])
        finally:
            if old is None:
                os.environ.pop("LECTURE_SAVE_REPORTS", None)
            else:
                os.environ["LECTURE_SAVE_REPORTS"] = old


if __name__ == "__main__":
    unittest.main()
