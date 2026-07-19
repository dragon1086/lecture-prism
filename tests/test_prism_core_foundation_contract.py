from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrismCoreFoundationContractTest(unittest.TestCase):
    def test_runtime_docs_distinguish_classroom_paper_and_live(self):
        text = (ROOT / "docs/runtime-profiles.md").read_text(encoding="utf-8")
        for phrase in (
            "classroom",
            "KR/US",
            "CREATED → PREVIEWED → SUBMITTED → ACCEPTED",
            "ACCEPTED는 체결이 아닙니다",
            "미체결",
            "paper/live에서는 mock",
            "UNKNOWN",
            "classroom과 backtest",
        ):
            self.assertIn(phrase, text)

    def test_architecture_documents_stateful_core_and_follow_on_boundaries(self):
        text = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
        for phrase in (
            "SQLite",
            "재시작",
            "provenance",
            "포트폴리오 전체 high-water",
            "청산 우선",
            "KRW",
            "USD",
            "한국 주식 수량은 정수",
            "UNKNOWN",
            "후속 과제",
            "대시보드",
            "KIS",
            "Toss",
        ):
            self.assertIn(phrase, text)

    def test_part3_uses_agent_prompts_for_replay_evidence_and_safety(self):
        text = (ROOT / "lecture/exercises/part3_실습가이드.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "classroom 전체 사이클",
            "미체결 → 체결 → 청산",
            "broker_orders",
            "fills",
            "positions",
            "realized_trades",
            "대시보드의 한계",
            "live_blocked",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
