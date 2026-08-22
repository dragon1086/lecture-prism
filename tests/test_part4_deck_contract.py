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
            "MY_STRATEGY.md",
            "30초 버전",
            "다음 수업에 가져오세요",
        ):
            self.assertIn(phrase, self.part3_close)

        self.assertIn("MY_STRATEGY.md", self.instructor_script)

    def test_part_four_opens_with_student_strategy_and_instructor_demo_briefs(self):
        prompt_section = self.prompts.split("## P4-KIS", 1)[0]
        for phrase in (
            "MY_STRATEGY.md",
            "진입·분석·청산·리스크",
            "오늘 구현할 한 가지",
            "아직 코드",
        ):
            self.assertIn(phrase, prompt_section)
        self.assertNotIn("내 문장:", prompt_section)

        for phrase in (
            "P4-D0 · 강사 시연 계획 정리하기",
            "터틀 20일 신고가 진입과 10일 저가 청산",
            "ATR 손절과 위험 기준 수량",
            "KOSPI 장세별 진입 강도",
            "API 키 없는 DART RSS와 확인된 공시 입력",
            "작업 순서",
            "담당 파일",
            "확인할 증거",
        ):
            self.assertIn(phrase, self.instructor_script)

        slide = self._slide("P4-S03")
        self.assertIn("MY_STRATEGY.md", slide)
        self.assertIn("오늘 시연할 네 작업", slide)

    def test_instructor_has_a_self_contained_read_only_kis_prompt(self):
        for phrase in (
            "강사 선택 시연 P4-KIS",
            "KIS real",
            "삼성전자 005930 한 종목",
            "기관·외국인·개인 순매수",
            "수급 섹션만",
            "simulation",
            "주문·취소·정정·잔고·계좌 API 호출은 0회",
        ):
            self.assertIn(phrase, self.instructor_script)
        self.assertNotIn("[P4-KIS]", self.instructor_script)

    def test_part_four_teaches_the_vibe_coding_and_development_foundations(self):
        for phrase in (
            "혼자서 다음 수정",
            "run_pipeline()",
            "함수는 값을 받아 일을 하고 결과를 돌려줍니다",
            "에이전트가 바깥 정보를 읽으려면 도구가 필요합니다",
            "디버깅은 처음 문제가 생긴 곳을 찾는 일입니다",
            "로그를 보면 어느 단계까지 실행됐는지 알 수 있습니다",
            "prism.db 안에는 성격이 다른 세 개의 표가 있습니다",
            "로컬은 내 컴퓨터, 서버는 계속 켜 둔 별도 컴퓨터입니다",
            "3분 뒤",
        ):
            self.assertIn(phrase, self.sources)

    def test_beginner_foundations_show_the_real_project_and_data_handoffs(self):
        """Slides 6–9 must let a first-time reader follow this repository."""
        overview = self._slide("P4-S05")
        for phrase in (
            "전체 실행 지도",
            "한 번 실행하면",
            "후보 목록",
            "분석 보고서",
            "진입 시나리오",
            "매매 결과",
            "DB 기록",
        ):
            with self.subTest(slide="P4-S05", phrase=phrase):
                self.assertIn(phrase, overview)

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
            "run_pipeline()",
            "screening.py.run_screening()",
            "analysis.py.run_analysis_report()",
            "buy_agent.py.run_buy_agent()",
            "trading.py.run_trading()",
            "feedback.py.run_feedback()",
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
            "데이터를 담는 모양",
            "list",
            "dict",
            "str",
            "bool",
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

        configuration = self._slide("P4-S10")
        self.assertNotIn("안전 조건", configuration)
        for phrase in ("반드시 지킬 원칙", "실행할 때 고르는 값", "mock", "simulation"):
            self.assertIn(phrase, configuration)

    def test_beginner_foundations_do_not_require_an_ide_for_code_or_settings(self):
        directory = self._slide("P4-S06")
        for phrase in (
            "GitHub·브라우저",
            "10~20줄",
            "입력·반환값",
            "변경 전후",
        ):
            self.assertIn(phrase, directory)

        configuration = self._slide("P4-S10")
        for phrase in (
            ".env.example",
            "기본 텍스트 편집기",
            "직접 입력",
            "준비됨 / 비어 있음 / 형식 오류",
            ".gitignore",
            "로컬 파일 읽기까지 막지는 않습니다",
        ):
            self.assertIn(phrase, configuration)

    def test_read_only_kis_setup_uses_only_env_credentials_and_redacted_status(self):
        kis_prompt = self.prompts.split("## P4-01", 1)[0].split("## P4-KIS", 1)[1]
        for phrase in (
            "P4-KIS 선택 준비 프롬프트",
            ".env.example",
            "운영체제의 기본 텍스트 편집기",
            "App Key와 App Secret",
            "LECTURE_KIS_MODE",
            "paper면 demo, real이면 real",
            "계좌번호와 HTS ID는 필요하지",
            "준비됨 / 비어 있음 / 형식 오류",
            "값 자체를 출력하지",
            ".gitignore",
        ):
            self.assertIn(phrase, kis_prompt)

        for source in (kis_prompt, self.instructor_script):
            self.assertIn("kis_devlp.yaml", source)
            self.assertIn("모의·실거래 브로커 심화", source)

    def test_p4_01_personalizes_the_shared_map_to_the_student_strategy(self):
        for text in (self.prompts, self.instructor_script):
            for phrase in (
                "P4-01",
                "내 전략",
                "담당 파일",
                "담당 함수",
                "입력",
                "돌려주는 결과",
                "영향 범위",
            ):
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, text)

        prompt_section = self.prompts.split("## P4-02", 1)[0].split("## P4-01", 1)[1]
        self.assertIn("P4-00에서 고른", prompt_section)
        self.assertIn("공통 지도", prompt_section)
        self.assertIn("개인화", prompt_section)
        self.assertIn("담당 함수 주변 10~20줄", prompt_section)
        self.assertIn("파일 전체를 길게 복사하지 마", prompt_section)

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
            "P4-00 · MY_STRATEGY.md에서 오늘 바꿀 한 가지 정하기",
            "P4-01 · 내 전략이 들어갈 파일과 함수 찾기",
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

    def test_slide_fourteen_teaches_six_visual_agent_patterns_and_the_real_project_shape(self):
        slide = self._slide("P4-S14")

        for phrase in (
            "Sequential / Pipeline",
            "Concurrent / Fan-out·Fan-in",
            "Routing / Handoff",
            "Orchestrator–Workers",
            "Maker–Checker",
            "Magentic / Adaptive planning",
            "screening → analysis → buy → trading → feedback",
            "asyncio.gather",
            "순차 파이프라인",
            "병렬 전문가",
            "Anthropic",
            "Microsoft",
            "OpenAI",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)

        diagrams = re.findall(r'<img\b[^>]*class="pattern-diagram"[^>]*>', slide)
        self.assertEqual(6, len(diagrams))
        for diagram in diagrams:
            self.assertIn('data-fullscreenable="true"', diagram)
            self.assertIn('tabindex="0"', diagram)

        for phrase in (
            "Sequential / Pipeline",
            "Concurrent / Fan-out·Fan-in",
            "Routing / Handoff",
            "Orchestrator–Workers",
            "Maker–Checker",
            "Magentic / Adaptive planning",
        ):
            self.assertIn(phrase, self.prompts)
            self.assertIn(phrase, self.instructor_script)

    def test_slide_twenty_one_connects_prompting_to_a_spec_and_verification_loop(self):
        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        self.assertEqual(55, len(rows))
        row = next(item for item in rows if item["id"] == "P4-S21")
        self.assertIn("명세", row["title"])
        self.assertEqual("P4-03", row["promptId"])

        slide = self._slide("P4-S21")
        for phrase in (
            "PRD / Spec",
            "작업·검증 계획",
            "설계",
            "구현",
            "검증",
            "피드백",
            "GitHub Spec Kit",
            "Anthropic",
            "OpenAI",
            "약 40만",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)
        self.assertIn('data-fullscreenable="true"', slide)
        self.assertIn('tabindex="0"', slide)

    def test_personal_practice_handoff_and_instructor_demo_use_observable_evidence(self):
        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        self.assertEqual(
            [f"P4-S{index:02d}" for index in range(1, 56)],
            [row["id"] for row in rows],
        )
        self.assertFalse(
            any("계산은 코드에 맡기고 시장 상황 설명은 AI에게 맡깁니다" in row["title"] for row in rows)
        )

        practice = next(row for row in rows if row["id"] == "P4-S25")
        evidence = next(row for row in rows if row["id"] == "P4-S26")
        demo_close = next(row for row in rows if row["id"] == "P4-S38")
        self.assertIn("한 파일만 바꿔", practice["title"])
        self.assertEqual("P4-05~P4-08", practice["promptId"])
        self.assertIn("달라진 결과", evidence["title"])
        self.assertEqual("P4-05~P4-08", evidence["promptId"])
        self.assertEqual("P4-05~P4-08", demo_close["promptId"])

        for phrase in (
            "P4-D1.md의 수정 전후 결과 표",
            "P4-D2.md의 입력 확인 표",
            "P4-D3.md의 market_condition 경로 표",
            "P4-D4.md에는 `사용 경로 / 수집 건수",
            "완료 / 폴백으로 검증 / 다음 작업",
            "결과가 아직 없으면",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.sources + self.instructor_script)

        for stale in (
            "예상과 다르면 로그에서 첫 차이를 찾습니다",
            "데이터 필드를 확인하지 않고 계산부터 만들면 중단시키고",
            "P4-D2로 같은 계좌자산",
            "P4-D3로 KOSPI 시황",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.sources + self.instructor_script)

    def test_external_evidence_is_filtered_before_llm_input_and_close_points_to_a_new_system(self):
        quality_flow = self._slide("P4-S36") + self._slide("P4-S37")
        for phrase in (
            "응답 정상 여부",
            "분석 질문과 관련 있는가",
            "날짜·출처·중복",
            "최대 3건",
            "통신 오류 문구",
            "임원 개인 사건",
            "출처 없는 AI 요약",
            "수집 건수",
            "제외 이유",
            "LLM에 넘긴 자료",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, quality_flow + self.instructor_script)

        close = self._slide("P4-S55")
        for phrase in (
            "lecture-prism",
            "prism-insight",
            "여러분만의 전략과 시스템",
            "정원 가꾸듯",
            "비공개",
            "GitHub 계정명",
            "munsangrok@gmail.com",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, close + self.instructor_script)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        closing_row = next(item for item in rows if item["id"] == "P4-S55")
        self.assertIn("여러분만의 전략과 시스템", closing_row["title"])

    def test_after_class_cloud_operations_are_a_three_slide_roadmap_not_a_telegram_feature(self):
        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        by_id = {row["id"]: row for row in rows}

        self.assertEqual("P4-15", by_id["P4-S54"]["promptId"])
        self.assertIsNone(by_id["P4-S52"]["promptId"])
        self.assertIsNone(by_id["P4-S53"]["promptId"])
        self.assertIn("after-class-cloud-operations-roadmap.png", self._slide("P4-S52"))
        self.assertIn("## P4-15", self.prompts)
        self.assertNotIn("class TelegramNotifier", self.sources)

    def test_instructor_uses_one_sequential_prompt_for_all_four_demo_checkpoints(self):
        start = self.instructor_script.index("P4-D1~P4-D4 · 강사 통합 시연")
        end = self.instructor_script.index("**이 구간의 완료 기준:**", start)
        block = self.instructor_script[start:end]
        self.assertEqual(1, block.count("```text"))
        for phrase in (
            "D1 → D2 → D3 → D4",
            "P4-D1 · 터틀",
            "P4-D2 · ATR",
            "P4-D3 · KOSPI",
            "P4-D4 · DART RSS",
            "PRD",
            "작업 계획",
            "검증 계획",
            "설계",
            "구현",
            "검증",
            "피드백",
            "tasks/instructor-demo/",
            "개선 루프는 한 번만",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)

        d4 = block[block.index("P4-D4 · DART RSS") :]
        for phrase in (
            "DART RSS",
            "API 키가 필요하지",
            "urllib.request",
            "xml.etree.ElementTree",
            "회사별 공시",
            "저장한 XML",
            "고정 교육용 예제",
            "자동 재시도",
        ):
            self.assertIn(phrase, d4)
        self.assertNotIn("OpenDART API를 연결", d4)

    def test_student_tracks_reuse_my_strategy_and_harness_without_placeholder_strategy(self):
        start = self.prompts.index("## P4-04")
        end = self.prompts.index("## P4-09", start)
        block = self.prompts[start:end]
        for phrase in (
            "MY_STRATEGY.md",
            "docs/harness-lite.md",
            "Strategy Harness Lite",
            "P4-04가 정한 트랙 계획",
            "한 트랙 수정 → 데모 검증 → 전후 비교",
            "다음 트랙",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, block)
        self.assertNotIn("내 전략: [", block)
        self.assertNotIn("내 원칙: [", block)
        self.assertNotIn("tasks/student-strategy-plan.md", block)

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

    def test_part_four_uses_the_real_subscriber_question_as_the_instructor_demo(self):
        combined = self.sources + self.prompts + self.instructor_script
        for phrase in (
            "터틀 추세추종",
            "20일 신고가",
            "10일 저가",
            "ATR 손절",
            "한 거래 허용손실",
            "KOSPI 시황",
            "리포트 캡처",
            "공시",
            "종목·작성일·출처·핵심 주장·유효기간",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

        self.assertIn("P4-D1~P4-D4 · 강사 통합 시연", self.instructor_script)
        for checkpoint in ("P4-D1 · 터틀", "P4-D2 · ATR", "P4-D3 · KOSPI", "P4-D4 · DART RSS"):
            with self.subTest(checkpoint=checkpoint):
                self.assertIn(checkpoint, self.instructor_script)
                self.assertNotIn(checkpoint, self.prompts)
        self.assertNotIn("수강생_붙여넣기_프롬프트_파트4.md#p4-d", self.instructor_script)

    def test_every_slide_tells_the_learner_where_the_copy_prompt_is(self):
        slides = re.findall(r'<section[^>]*class="slide[^>]*>.*?</section>', self.assembled, re.S)
        self.assertGreater(len(slides), 40)
        missing = [index + 1 for index, slide in enumerate(slides) if 'class="prompt-guide"' not in slide]
        self.assertEqual([], missing, f"slides without prompt guide: {missing}")
        for slide in slides:
            self.assertRegex(slide, r"수강생 자료|강사 자료|다음 붙여넣기|붙여넣지 않습니다")

    def test_instructor_demo_prompt_guides_do_not_point_to_student_materials(self):
        prompt_id = "P4-D1~P4-D4"
        self.assertIn(f"강사 자료 → {prompt_id}", self.assembled)
        self.assertNotIn(f"수강생 자료 → {prompt_id}", self.assembled)
        self.assertIn(prompt_id, self.instructor_script)
        self.assertNotIn(prompt_id, self.prompts)

    def test_practice_slides_pair_instructor_and_student_actions(self):
        self.assertGreaterEqual(self.sources.count('class="instructor-action"'), 8)
        self.assertEqual(
            self.sources.count('class="instructor-action"'),
            self.sources.count('class="student-action"'),
        )
        for phrase in (
            "강사 시연",
            "수강생 실습",
            "통합 프롬프트",
            "하네스가 고른 현재 트랙",
        ):
            self.assertIn(phrase, self.sources)

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
