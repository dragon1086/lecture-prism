import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECK_ROOT = ROOT / "강의자료"
SOURCE_ROOT = DECK_ROOT / "deck-src"


class Part4DeckContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (SOURCE_ROOT / "deck-manifest.json").read_text(encoding="utf-8")
        )
        files = [
            SOURCE_ROOT / module["file"]
            for module in cls.manifest["decks"]["part4"]["modules"]
        ]
        cls.sources = "\n".join(path.read_text(encoding="utf-8") for path in files)
        cls.assembled = (DECK_ROOT / "파트4_슬라이드.html").read_text(encoding="utf-8")
        cls.prompts = (
            ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트4.md"
        ).read_text(encoding="utf-8")
        cls.instructor_script = (DECK_ROOT / "강사용_실습진행_스크립트.md").read_text(
            encoding="utf-8"
        )
        cls.part3_close = (
            SOURCE_ROOT / "part3" / "99-close.html"
        ).read_text(encoding="utf-8")

    def test_slide_four_is_the_shared_read_only_kis_enrichment_lab(self):
        slide = self._slide("P4-S04")
        for phrase in (
            "공통 실습 P4-KIS",
            "KIS real",
            "005930",
            "기관·외국인·개인",
            "가장 최근 영업일",
            "수급 섹션만",
            "simulation",
            "주문·취소·정정·잔고·계좌",
            "0회",
        ):
            self.assertIn(phrase, slide)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        row = next(item for item in rows if item["id"] == "P4-S04")
        self.assertEqual("P4-KIS", row["promptId"])
        self.assertIn("KIS 실제 수급", row["title"])
        self.assertIn('data-slide-id="P4-S04"', self.assembled)
        self.assertIn("KIS 실제 수급", self.assembled)

    def test_screen_fit_and_fullscreen_image_viewer_match_part_three(self):
        head = (SOURCE_ROOT / "shared" / "part4-head.html").read_text(
            encoding="utf-8"
        )
        tail = (SOURCE_ROOT / "shared" / "part4-tail.html").read_text(
            encoding="utf-8"
        )

        for phrase in (
            "--screen-scale",
            "zoom: var(--screen-scale)",
            "body.viewer-open",
            ".image-viewer",
        ):
            self.assertIn(phrase, head)

        for phrase in (
            "updateScreenScale",
            "requestFullscreen",
            "fullscreenchange",
            "section.slide img",
            "image.dataset.fullscreenable",
        ):
            self.assertIn(phrase, tail)

        self.assertIn("--screen-scale", self.assembled)
        self.assertIn("requestFullscreen", self.assembled)

    def test_part_three_closes_with_a_concrete_part_four_preparation_task(self):
        for phrase in (
            "파트 4 준비",
            "고치고 싶은 것",
            "한 문장",
            "다음 수업에 가져오세요",
        ):
            self.assertIn(phrase, self.part3_close)

        self.assertIn("파트 4에서 고치고 싶은 것", self.instructor_script)

    def test_part_four_teaches_the_vibe_coding_and_development_foundations(self):
        for phrase in (
            "자립형 바이브코더",
            "main.py가 필요한 이유",
            "함수끼리 맞물리는 약속",
            "에이전트는 어떻게 도구를 쓰고 결과를 넘길까요",
            "디버깅은 원인을 좁히는 일입니다",
            "로그는 프로그램이 남긴 작업 일지입니다",
            "DB와 테이블은 실행 결과를 다시 꺼내 쓰는 곳입니다",
            "로컬과 서버는 실행 장소가 다릅니다",
            "3분 뒤",
        ):
            self.assertIn(phrase, self.sources)

    def test_beginner_foundations_show_the_real_project_and_data_handoffs(self):
        """Slides 6–9 must let a first-time reader follow this repository."""
        directory = self._slide("P4-S06")
        for phrase in (
            "main.py",
            "screening.py",
            "analysis.py",
            "buy_agent.py",
            "trading.py",
            "feedback.py",
            "db.py",
            "dashboard.py",
            "tests/",
            "lecture/",
        ):
            with self.subTest(slide="P4-S06", phrase=phrase):
                self.assertIn(phrase, directory)

        entry = self._slide("P4-S07")
        for phrase in (
            "run_screening",
            "run_analysis_report",
            "run_buy_agent",
            "run_trading",
            "run_feedback",
            "후보 목록",
            "분석 보고서",
            "진입 시나리오",
            "매매 결과",
            "DB 기록",
        ):
            with self.subTest(slide="P4-S07", phrase=phrase):
                self.assertIn(phrase, entry)

        function = self._slide("P4-S08")
        for phrase in (
            "run_screening",
            "target_ticker",
            "use_real",
            "list[str]",
            "입력",
            "반환",
        ):
            with self.subTest(slide="P4-S08", phrase=phrase):
                self.assertIn(phrase, function)

        connection = self._slide("P4-S09")
        for phrase in (
            "screening",
            "import",
            "run_screening",
            "candidates",
            "return",
            "다음 단계",
        ):
            with self.subTest(slide="P4-S09", phrase=phrase):
                self.assertIn(phrase, connection)

    def test_agent_slides_distinguish_roles_from_tools_and_show_real_handoffs(self):
        definition = self._slide("P4-S11")
        for phrase in ("AgentSpec", "수급 분석가", "supply_summary", "JSON"):
            with self.subTest(slide="P4-S11", phrase=phrase):
                self.assertIn(phrase, definition)

        tool_call = self._slide("P4-S12")
        for phrase in (
            "evidence",
            "llm_complete",
            "extract_json",
            '{"summary": "..."}',
            "규칙 보고서 폴백",
        ):
            with self.subTest(slide="P4-S12", phrase=phrase):
                self.assertIn(phrase, tool_call)

        handoff = self._slide("P4-S13")
        for phrase in (
            "technical_summary",
            "supply_summary",
            "executive_summary",
            "run_buy_agent",
        ):
            with self.subTest(slide="P4-S13", phrase=phrase):
                self.assertIn(phrase, handoff)

        harness = self._slide("P4-S15")
        for phrase in (
            "MY_STRATEGY.md",
            "lecture-strategy-interviewer",
            "lecture-strategy-implementer",
            "lecture-strategy-verifier",
            "한 파일",
        ):
            with self.subTest(slide="P4-S15", phrase=phrase):
                self.assertIn(phrase, harness)

    def test_part_four_prompts_cover_inspection_change_debug_db_and_local_schedule(self):
        for heading in (
            "P4-00 · 파트3에서 가져온 변경 아이디어 정리하기",
            "P4-01 · 프로젝트 지도와 Python 연결 구조 읽기",
            "P4-02 · 에이전트·도구·통신 원리 확인하기",
            "P4-03 · 내 요청을 개발 프롬프트로 바꾸기",
            "P4-09 · 로그로 원인을 좁혀 디버깅하기",
            "P4-10 · DB와 테이블에서 실행 기록 확인하기",
            "P4-11 · 3분 뒤 로컬 예약 실행 설계하기",
            "P4-12 · 승인 후 예약하고 증거 확인하기",
            "P4-13 · 임시 예약 삭제하고 반복 주기 설계하기",
        ):
            self.assertIn(heading, self.prompts)

        for safety_phrase in (
            "mock·simulation",
            "변경 목록을 먼저 보여줘",
            "내가 승인하기 전에는 코드 수정이나 예약 변경을 하지 마",
            "로그 파일",
            "DB의 새 기록",
            "임시 예약을 삭제",
        ):
            self.assertIn(safety_phrase, self.prompts)

    def test_strategy_tracks_and_evidence_loop_remain_in_the_reworked_course(self):
        for phrase in (
            "트랙 A",
            "트랙 B",
            "트랙 C",
            "트랙 D",
            "한 파일",
            "수정 전후",
            "mock",
            "simulation",
        ):
            self.assertIn(phrase, self.sources + self.prompts)

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


if __name__ == "__main__":
    unittest.main()
