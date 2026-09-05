"""Regression checks for learner-facing current-architecture documentation."""

from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]

DOCUMENTS = {
    "readme": ROOT / "README.md",
    "start": ROOT / "START_HERE.md",
    "part3": ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md",
    "part4": ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트4.md",
    "architecture": ROOT / "docs" / "architecture.md",
    "runtime": ROOT / "docs" / "runtime-profiles.md",
    "api": ROOT / "docs" / "api-keys.md",
    "brokers": ROOT / "docs" / "broker-adapters.md",
    "defaults": ROOT / "docs" / "defaults-and-philosophy.md",
    "llm": ROOT / "docs" / "why-multi-agent.md",
    "preflight": ROOT / "docs" / "runtime-execution-preflight.md",
}

MAINTAINED_VISUALS = (
    ROOT / "docs" / "assets" / "readme" / "strategy-to-kis.png",
    ROOT / "docs" / "assets" / "readme" / "system-result.png",
    ROOT / "docs" / "assets" / "readme" / "runtime-architecture-map.png",
    ROOT / "docs" / "assets" / "readme" / "module-guide.png",
    ROOT / "docs" / "assets" / "readme" / "optional-integrations-safety.png",
)


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG with IHDR: {path}")
    return struct.unpack(">II", header[16:24])


class DocumentationArchitectureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = {
            name: path.read_text(encoding="utf-8")
            for name, path in DOCUMENTS.items()
        }

    def test_entry_points_name_the_two_current_learning_paths(self):
        for name in ("readme", "start", "architecture"):
            with self.subTest(document=name):
                self.assertIn("기본 학습 경로", self.text[name])
                self.assertIn("상태 기반 고급 경로", self.text[name])

        self.assertIn("classroom", self.text["start"])
        self.assertIn("backtest", self.text["architecture"])
        self.assertIn("paper", self.text["architecture"])
        self.assertIn("live", self.text["architecture"])

    def test_docs_keep_quantitative_rules_and_llm_veto_separate(self):
        combined = "\n".join(self.text.values())
        self.assertIn("LLM은 BUY를 HOLD로만", combined)
        self.assertIn("규칙이 소유", combined)
        self.assertNotIn("기술·뉴스·전략은 LLM 에이전트", combined)

    def test_course_docs_separate_report_agents_from_buy_agent(self):
        combined = "\n".join(self.text.values())
        for filename in ("analysis_agents.py", "buy_agent.py", "trading.py"):
            self.assertIn(filename, combined)
        for retired in (
            "기술·뉴스·리스크의 정성 역할을 한 번의 구조화 호출",
            "종목당 단일 구조화 호출",
            "강의용 3-에이전트 경량판",
        ):
            self.assertNotIn(retired, combined)

    def test_docs_describe_broker_lifecycle_without_overclaiming_live_e2e(self):
        combined = "\n".join(self.text.values())
        for phrase in (
            "매수·매도·조회·취소·재시작 reconcile",
            "KIS",
            "Toss",
            "UNKNOWN",
            "fixture",
            "실제 계좌 E2E",
        ):
            self.assertIn(phrase, combined)
        self.assertNotIn("브로커 lifecycle은 후속 과제", combined)

    def test_course_docs_do_not_retain_retired_oauth_or_root_universe_claims(self):
        self.assertNotIn("ChatGPT 어댑터 구조 확인 (CH1 라이브 데모 · 후속 과제)", self.text["part3"])
        self.assertNotIn("약 2,700종목", self.text["defaults"])
        self.assertIn(
            "프로젝트 첫 폴더에 있는 screening.py",
            self.text["part4"],
        )
        self.assertNotIn("prism_core/screening.py", self.text["part4"])

    def test_preflight_uses_the_actual_kis_https_ports(self):
        self.assertIn(
            "openapivts.koreainvestment.com:29443",
            self.text["preflight"],
        )
        self.assertIn(
            "openapi.koreainvestment.com:9443",
            self.text["preflight"],
        )

    def test_maintained_architecture_visuals_are_large_pngs(self):
        for asset in MAINTAINED_VISUALS:
            with self.subTest(asset=asset.name):
                self.assertTrue(asset.is_file())
                width, height = _png_dimensions(asset)
                self.assertGreaterEqual(width, 1200)
                self.assertGreaterEqual(height, 675)


if __name__ == "__main__":
    unittest.main()
