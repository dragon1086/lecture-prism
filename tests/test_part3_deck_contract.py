import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECK_ROOT = ROOT / "강의자료"
SOURCE_ROOT = DECK_ROOT / "deck-src"
PART3_ROOT = SOURCE_ROOT / "part3"
HEAD = SOURCE_ROOT / "shared" / "part3-head.html"
TAIL = SOURCE_ROOT / "shared" / "part3-tail.html"


EXPECTED_CAPTION_PHRASES = {
    "full-pipeline-overview.png": "시장과 후보 선별부터",
    "market-pulse-batch-control-overview.png": "CAN SLIM의 M",
    "distribution-day-state-transitions.png": "전일보다 0.2% 이상",
    "screening-six-triggers-overview.png": "서로 다른 움직임",
    "candidate-screening-reranking-overview.png": "네 점수를 시장 체제별 비중",
    "trading-regime-entry-overview.png": "서로 목적이 다른 시장 분류",
    "screening-analysis-deep-dive.png": "여섯 방향의 보고서",
    "can-slim-company-supply-checks.png": "C·A·N·S",
    "can-slim-leadership-market-checks.png": "L·I·M",
    "entry-gates-overview.png": "Enter 또는 No Entry",
    "pyramiding-portfolio-overview.png": "물타기가 아니라",
    "trading-exit-overview.png": "여러 도구가 나누어",
    "position-protection-loops.png": "docker/crontab에는 등록되어 있지",
    "feedback-reentry-overview.png": "자율 강화학습이 아니라",
}


class Part3DeckContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.head = HEAD.read_text(encoding="utf-8")
        cls.tail = TAIL.read_text(encoding="utf-8")
        cls.sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(PART3_ROOT.glob("*.html"))
        )

    def test_screen_fit_and_fullscreen_viewer_are_declared(self):
        self.assertIn("--screen-scale", self.head)
        self.assertIn("updateScreenScale", self.tail)
        self.assertIn("requestFullscreen", self.tail)
        self.assertIn("fullscreenchange", self.tail)
        self.assertIn("image-viewer", self.head)

    def test_four_module_comparison_assets_are_referenced_without_card_grid(self):
        for name in ("screening", "analysis", "trading", "feedback"):
            filename = f"lecture-compare-{name}.png"
            self.assertIn(filename, self.sources)
            asset = DECK_ROOT / "assets" / filename
            self.assertTrue(asset.exists(), filename)
            self.assertEqual((1920, 1080), self._png_size(asset))

        comparison_sections = re.findall(
            r'<section[^>]*class="[^"]*comparison-slide[^"]*"[^>]*>.*?</section>',
            self.sources,
            flags=re.S,
        )
        self.assertEqual(4, len(comparison_sections))
        self.assertTrue(all("pattern-grid" not in section for section in comparison_sections))

    def test_all_architecture_captions_match_source_document_scope(self):
        seen = set()
        for filename, phrase in EXPECTED_CAPTION_PHRASES.items():
            pattern = re.compile(
                rf'<img[^>]+src="[^"]*{re.escape(filename)}"[^>]*>\s*'
                rf'<p class="caption">(.*?)</p>',
                flags=re.S,
            )
            matches = pattern.findall(self.sources)
            self.assertGreaterEqual(len(matches), 1, filename)
            caption = re.sub(r"<[^>]+>", "", matches[0])
            self.assertIn(phrase, caption, filename)
            seen.add(filename)
        self.assertEqual(set(EXPECTED_CAPTION_PHRASES), seen)

    def test_module_two_teaches_report_agents_and_module_three_owns_buy_decision(self):
        for phrase in (
            "analysis_agents.py",
            "전문 에이전트 6개",
            "편집 에이전트",
            "buy_agent.py",
            "Enter / No Entry",
        ):
            self.assertIn(phrase, self.sources)
        self.assertNotIn("선택적 AI 한 번으로 줄였습니다", self.sources)
        self.assertNotIn("_run_combined_llm_agent", self.sources)

    def test_slide_34_explains_memory_results_in_plain_investor_language(self):
        match = re.search(
            r"<!-- P3-S34\b.*?<section\b.*?</section>",
            self.sources,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        slide = match.group(0)

        for phrase in (
            "AI가 과거 매매 교훈을 읽고 판단한 거래",
            "수익으로 끝난 거래의 비율",
            "거래한 시기와 시장 흐름이 달랐을 수 있음",
            "기억은 정답지가 아닙니다",
        ):
            self.assertIn(phrase, slide)

        for phrase in (
            "메모리 참조 거래",
            "비참조 거래",
            "관찰 상관관계",
            "인과 증명",
            "표본 선택",
            "시장 국면",
        ):
            self.assertNotIn(phrase, slide)

    @staticmethod
    def _png_size(path: Path) -> tuple[int, int]:
        with path.open("rb") as image:
            signature = image.read(24)
        if signature[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"not a PNG: {path}")
        return struct.unpack(">II", signature[16:24])


if __name__ == "__main__":
    unittest.main()
