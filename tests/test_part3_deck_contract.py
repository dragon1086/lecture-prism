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

    def test_prompt_guides_appear_only_on_part_three_practice_slides(self):
        expected_prompt_ids = {
            slide["id"]: slide["promptId"]
            for module in self.manifest["decks"]["part3"]["modules"]
            for slide in module["slides"]
        }
        slides = re.findall(
            r'<section data-slide-id="([^"]+)"[^>]*class="slide[^>]*>(.*?)</section>',
            self.assembled,
            flags=re.S,
        )

        self.assertNotIn("지금은 개념을 확인합니다", self.assembled)
        for slide_id, slide in slides:
            with self.subTest(slide=slide_id):
                if expected_prompt_ids[slide_id]:
                    self.assertIn('class="prompt-guide"', slide)
                else:
                    self.assertNotIn('class="prompt-guide"', slide)

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

    def test_first_run_source_map_is_a_simple_linear_pipeline(self):
        source_map = (DECK_ROOT / "assets" / "lecture-prism-source-map.svg").read_text(
            encoding="utf-8"
        )
        for phrase in (
            'id="lecture-prism-source-map-title"',
            'id="lecture-prism-source-map-desc"',
            "main.py",
            "screening.py",
            "analysis.py",
            "trading.py",
            "feedback.py",
            "prism.db",
            "시작과 순서",
            "후보 고르기",
            "분석 보고서",
            "가상 매매 판단",
            "결과를 저장하고",
            "보여 줌",
            "실행 환경",
            "runtime_config.py",
            "llm_provider.py",
            "데이터·보고서",
            "data_source.py",
            "report_writer.py",
            "저장·화면",
            "prism.db",
            "dashboard.py",
            "선택 기능·참고",
            "notifications.py · Discord·Telegram",
            "brokers/ · cores/",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, source_map)
        self.assertNotIn('id="grid"', source_map)

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

    def test_slide_five_allows_discord_or_telegram_report_setup(self):
        slide = self._slide("P3-S05")

        self.assertIn("Discord 또는 Telegram", slide)
        self.assertIn("보고 채널", slide)
        self.assertIn(".env", slide)
        self.assertIn("채팅에 붙여넣지", slide)

    def test_learning_outcomes_are_visible_before_the_first_execution(self):
        slide = self._slide("P3-S04")

        for phrase in (
            "오늘 수업에서",
            "직접 확인하는 네 가지",
            "전체 흐름을 봅니다",
            "AI와 코드의 역할",
            "안전장치를 확인합니다",
            "내 컴퓨터에서 실행합니다",
            "후보 찾기 → 분석",
            "매매 판단 → 기록",
            "AI는 의견을 줍니다.",
            "코드는 주문 전 조건을 확인합니다.",
            "손절·수량·주문 접수와",
            "체결을 따로 확인합니다.",
            "API 키 없이 연습 데이터로",
            "가상 매매까지 실행합니다.",
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
        self.assertEqual([f"P3-S{number:02d}" for number in range(1, 47)], slide_ids)

    def test_module_two_shows_multiple_collection_paths_and_one_kis_example(self):
        slide = self._slide("P3-S22")
        asset = DECK_ROOT / "assets" / "prism-data-enrichment-lab.png"

        for phrase in (
            "데이터 보강은 빈칸 하나부터",
            "Open API",
            "웹 크롤링",
            "파일과 데이터베이스",
            "MCP 연결",
            "KIS",
            "기관·외국인·개인",
            "실제 수급도 함께 보면 더 좋겠다",
            "이번 주 마지막 장",
            "가능한 분만",
            "KIS App Key와 App Secret",
            "다음 주",
            "Part 4 초반",
            "기본 보고서의 수급 설명",
            "기관·외국인·개인 순매수",
            "주문은 하지 않습니다",
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
        self.assertEqual([f"P3-S{number:02d}" for number in range(1, 47)], manifest_ids)

        expected_titles = {
            "P3-S40": "매일 돌리려면 다섯 가지를 따로 챙겨야 합니다",
            "P3-S41": "내 컴퓨터에서는 이 순서로 준비 상태를 확인합니다",
            "P3-S42": "대시보드에서는 실행 결과 세 곳만 확인합니다",
            "P3-S43": "자동매매는 수익보다 먼저 망하지 않는 시스템이어야 합니다",
            "P3-S44": "후보부터 실제 성과까지 남기면 하나의 판단을 다시 볼 수 있습니다",
            "P3-S45": "시간이 지난 기록을 검증해 다음 정책을 고칩니다",
            "P3-S46": "파트 4에서 고치고 싶은 것을 한 문장으로 정해 옵니다",
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
        slide = self._slide("P3-S46")

        self.assertIn("파트 4 준비", slide)
        self.assertIn("고치고 싶은 것", slide)
        self.assertIn("내 전략에서 ___을 ___하게 바꾸고 싶다", slide)
        self.assertIn("다음 수업에 가져오세요", slide)
        self.assertIn("한국투자증권(KIS)", slide)
        self.assertIn("한국투자증권(KIS) 모의투자 또는 실전투자용 App Key와 App Secret", slide)
        self.assertIn("계좌번호·HTS ID는 필요하지 않습니다", slide)
        self.assertNotIn("<h1>Q&amp;A</h1>", slide)

    def test_logging_architecture_images_remain_full_size_and_expandable(self):
        expected_slides = {
            "P3-S44": (
                "prism-observable-data-catalog.png",
                "후보부터 실제 성과까지",
            ),
            "P3-S45": (
                "prism-logging-intelligence-architecture.png",
                "검증 가능한 증거",
            ),
        }

        for slide_id, (filename, phrase) in expected_slides.items():
            with self.subTest(slide_id=slide_id):
                asset = DECK_ROOT / "assets" / filename
                slide = self._slide(slide_id)
                self.assertTrue(asset.exists(), filename)
                self.assertEqual((1672, 941), self._png_size(asset))
                self.assertIn(filename, slide)
                self.assertIn(phrase, slide)
                self.assertIn('data-fullscreenable="true"', slide)
                self.assertIn('tabindex="0"', slide)

    def test_logging_slide_puts_survival_before_strategy_and_improvement(self):
        slide = self._slide("P3-S43")

        for phrase in (
            "수익보다 먼저",
            "망하지 않는 시스템",
            "파멸 가능성",
            "판단 전후를 빠짐없이 기록",
            "후보, 진입 이유, 시장 상태, 청산 기준, 매도 후 흐름",
            "기록으로 다음 결정을 고칩니다",
            "망하지 않으면, 더 나아질 기회가 남습니다",
        ):
            self.assertIn(phrase, slide)

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
