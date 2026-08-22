import json
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
ASSEMBLED_PART3 = DECK_ROOT / "파트3_슬라이드.html"
PART3_INDEX = SOURCE_ROOT / "part3-index.md"
CURRICULUM = ROOT / "lecture" / "curriculum.html"


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
        manifest = json.loads(
            (SOURCE_ROOT / "deck-manifest.json").read_text(encoding="utf-8")
        )
        part3_files = [
            SOURCE_ROOT / module["file"]
            for module in manifest["decks"]["part3"]["modules"]
        ]
        cls.sources = "\n".join(
            path.read_text(encoding="utf-8") for path in part3_files
        )
        cls.manifest = manifest
        cls.assembled = ASSEMBLED_PART3.read_text(encoding="utf-8")
        cls.index = PART3_INDEX.read_text(encoding="utf-8")
        cls.curriculum = CURRICULUM.read_text(encoding="utf-8")

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

    def test_cover_and_first_run_use_polished_visual_and_exact_prompt_route(self):
        slide_1 = self._slide("P3-S01")
        slide_4 = self._slide("P3-S05")
        cover_asset = DECK_ROOT / "assets" / "part3-cover-ai-console.png"

        self.assertIn("assets/part3-cover-ai-console.png", slide_1)
        self.assertNotIn("<svg", slide_1)
        self.assertTrue(cover_asset.exists())
        self.assertIn("P3-01 · API 키 없는 첫 성공", slide_4)
        self.assertIn("‘코딩 에이전트에 붙여넣기’ 블록 전체", slide_4)

    def test_learning_outcomes_are_visible_before_the_first_execution(self):
        slide = self._slide("P3-S04")

        for phrase in (
            "후보 찾기·분석·매매·기록",
            "각 단계의 파일",
            "AI 의견, 진입 판단, 주문 접수와 체결 확인",
            "감시·대사·기억 압축",
            "연습 데이터와 가상 체결",
        ):
            self.assertIn(phrase, slide)

    def test_module_openings_use_one_investment_decision_throughline(self):
        expected = {
            "P3-S08": "어제는 강세장, 오늘은 약세장입니다. 후보를 같은 기준으로 골라도 될까요?",
            "P3-S15": "이 종목을 사기 전에, 어떤 정보까지 확인하고 싶으세요?",
            "P3-S23": "AI가 매수를 추천했습니다. 이 의견만 믿고 주문해도 될까요?",
            "P3-S33": "어제 손절한 종목이 오늘 다시 떴습니다. 다시 사도 될까요?",
        }
        for slide_id, question in expected.items():
            self.assertIn(question, self._slide(slide_id), slide_id)

    def test_module_three_starts_with_a_concrete_vote_case_and_keeps_all_assets(self):
        scenario = self._slide("P3-S23")
        for phrase in (
            "BUY 8점",
            "70,000원",
            "77,000원",
            "63,000원",
            "손익비 1.0",
            "최소 1.5",
            "주문한다",
            "보류한다",
            "AI의 매수 의견만 보고 주문한다",
            "손익비를 확인한 뒤 주문을 보류한다",
            "수업을 위해 만든 가상 사례",
        ):
            self.assertIn(phrase, scenario)
        self.assertNotIn("안전문", self.sources)

        shifted_assets = {
            "P3-S24": "can-slim-company-supply-checks.png",
            "P3-S25": "can-slim-leadership-market-checks.png",
            "P3-S26": "entry-gates-overview.png",
            "P3-S27": "pyramiding-portfolio-overview.png",
            "P3-S28": "trading-exit-overview.png",
            "P3-S29": "position-protection-loops.png",
            "P3-S30": "lecture-compare-trading.png",
        }
        for slide_id, asset in shifted_assets.items():
            self.assertIn(asset, self._slide(slide_id), slide_id)
        self.assertIn("주문 의도", self._slide("P3-S31"))
        self.assertIn("P3-M3 블록 전체", self._slide("P3-S32"))

        slide_ids = re.findall(r"<!-- (P3-S\d{2})\b", self.sources)
        self.assertEqual([f"P3-S{number:02d}" for number in range(1, 44)], slide_ids)

    def test_module_two_shows_multiple_collection_paths_and_one_kis_example(self):
        slide = self._slide("P3-S22")
        asset = DECK_ROOT / "assets" / "prism-data-enrichment-lab.png"

        for phrase in (
            "데이터 보강은 빈칸 하나부터",
            "Open API",
            "웹 크롤링",
            "파일·DB",
            "MCP",
            "연결 통로",
            "KIS",
            "기관·외국인·개인",
            "수급 섹션만",
            "simulation",
            "주문 0회",
        ):
            self.assertIn(phrase, slide)
        self.assertIn("assets/prism-data-enrichment-lab.png", slide)
        self.assertTrue(asset.exists())
        self.assertEqual((1672, 941), self._png_size(asset))

    def test_operations_image_is_reserved_for_the_part_three_summary(self):
        slide_30 = self._slide("P3-S32")
        slide_37 = self._slide("P3-S39")

        self.assertNotIn("prism-auxiliary-operations-loop.png", slide_30)
        self.assertIn("prism-auxiliary-operations-loop.png", slide_37)
        self.assertEqual(
            1,
            self.sources.count("prism-auxiliary-operations-loop.png"),
        )

    def test_operations_readiness_slides_follow_auxiliary_operations_summary(self):
        slide_39 = self._slide("P3-S39")
        slide_40 = self._slide("P3-S40")
        slide_41 = self._slide("P3-S41")

        for phrase in (
            "여기까지는 한 번 실행",
            "매일 안전하게 반복",
        ):
            self.assertIn(phrase, slide_39, phrase)

        for phrase in (
            "정해진 때 시작하기",
            "보유 종목 살피기",
            "주문 결과 확인하기",
            "기록 정리하기",
            "이상 알려주기",
            "수업에서 할 일",
            "수업에서 하지 않을 일",
        ):
            self.assertIn(phrase, slide_40, phrase)

        for phrase in (
            "코딩 에이전트",
            "P3-M5",
            "준비 상태 점검",
            "operations.py doctor",
            "operations.py status",
            "준비됨",
            "준비 안 됨",
            "연습 데이터",
            "실데이터",
            "모의투자",
            "실거래",
            "실제 주문·취소 없이",
        ):
            self.assertIn(phrase, slide_41, phrase)

        for jargon in (
            "full 운영",
            "service manager",
            "long-lived service process",
            "CONDITIONAL",
            "READY",
            "configured / missing",
        ):
            self.assertNotIn(jargon, slide_39 + slide_40 + slide_41, jargon)

    def test_part_three_operations_ids_are_synced_across_manifest_index_curriculum_and_assembled_deck(self):
        manifest_rows = [
            slide
            for module in self.manifest["decks"]["part3"]["modules"]
            for slide in module["slides"]
        ]
        manifest_ids = [slide["id"] for slide in manifest_rows]
        self.assertEqual([f"P3-S{number:02d}" for number in range(1, 44)], manifest_ids)

        expected_titles = {
            "P3-S40": "매일 돌리려면 다섯 가지를 따로 챙겨야 합니다",
            "P3-S41": "내 컴퓨터에서는 이 순서로 준비 상태를 확인합니다",
            "P3-S42": "대시보드에서는 실행 결과 세 곳만 확인합니다",
            "P3-S43": "파트 4에서 고치고 싶은 것을 한 문장으로 정해 옵니다",
        }
        for slide_id, title in expected_titles.items():
            with self.subTest(slide_id=slide_id):
                self.assertIn(slide_id, self.index)
                self.assertIn(title, self.index)
                self.assertIn(f'data-slide-id="{slide_id}"', self.assembled)
                self.assertIn(title, self.assembled)

        for phrase in (
            "P3-M5",
            "doctor → simulation → paper → live",
            "mock / real_data / research / paper / live",
            "KIS 기준선",
            "Kiwoom 조건부",
            "Toss 공식 Open API와 WTS",
        ):
            self.assertIn(phrase, self.curriculum, phrase)

    def test_slide_34_teaches_memory_hygiene_without_performance_statistics(self):
        slide = self._slide("P3-S36")

        for phrase in (
            "기억은 많이 쌓는 것보다",
            "최근 교훈",
            "반복 교훈",
            "오래됐거나 도움이 안 되는 교훈",
        ):
            self.assertIn(phrase, slide)

        for phrase in (
            "최근 90일 거래 기록",
            "교훈을 읽음 70건",
            "교훈을 읽음 29건",
            "수익으로 끝난 거래의 비율",
            "손실의 원인",
        ):
            self.assertNotIn(phrase, slide)

    def test_dashboard_slide_uses_safe_mock_capture_and_teaches_three_reading_targets(self):
        slide = self._slide("P3-S42")
        asset = DECK_ROOT / "assets" / "lecture-prism-dashboard-mock.png"

        self.assertTrue(asset.exists())
        self.assertEqual((1600, 900), self._png_size(asset))
        for phrase in (
            "매매현황",
            "AI 분석 근거",
            "축적된 피드백",
            "로컬 시뮬레이션 기록",
            "실계좌 화면 아님",
        ):
            self.assertIn(phrase, slide)
        self.assertIn("assets/lecture-prism-dashboard-mock.png", slide)

    def test_final_slide_ends_with_one_immediate_application(self):
        slide = self._slide("P3-S43")

        self.assertIn("파트 4 준비", slide)
        self.assertIn("고치고 싶은 것", slide)
        self.assertIn("내 전략에서 ___을 ___하게 바꾸고 싶다", slide)
        self.assertIn("다음 수업에 가져오세요", slide)
        self.assertNotIn("<h1>Q&amp;A</h1>", slide)

    @classmethod
    def _slide(cls, slide_id: str) -> str:
        match = re.search(
            rf"<!-- {re.escape(slide_id)}\b.*?<section\b.*?</section>",
            cls.sources,
            flags=re.S,
        )
        if match is None:
            raise AssertionError(f"missing slide: {slide_id}")
        return match.group(0)

    @staticmethod
    def _png_size(path: Path) -> tuple[int, int]:
        with path.open("rb") as image:
            signature = image.read(24)
        if signature[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"not a PNG: {path}")
        return struct.unpack(">II", signature[16:24])


if __name__ == "__main__":
    unittest.main()
