import json
import re
import unittest
import xml.etree.ElementTree as ET
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

    def test_slide_four_is_an_optional_kis_supply_comparison_lab(self):
        slide = self._slide("P4-S05")
        for phrase in (
            "선택 실습 P4-KIS",
            "KIS 결과",
            "005930",
            "기관·외국인·개인",
            "일별 순매수와 가격",
            "수급 설명 전후",
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
        row = next(item for item in rows if item["id"] == "P4-S05")
        self.assertEqual("P4-KIS", row["promptId"])
        self.assertIn("KIS 실제 수급", row["title"])
        self.assertIn('data-slide-id="P4-S05"', self.assembled)
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

        slide = self._slide("P4-S04")
        self.assertIn("MY_STRATEGY.md", slide)
        self.assertIn("오늘 시연할 네 작업", slide)

    def test_part_four_second_slide_makes_the_student_takeaways_explicit(self):
        slide = self._slide("P4-S02")
        for phrase in (
            "내 전략을 내 컴퓨터에서",
            "직접 돌리고 계속 키워 갑니다",
            "코딩 에이전트 활용",
            "개발 기초",
            "문제 해결",
            "내 전략 구현",
            "서버 구축·24시간 운영",
            "예약·서버·감시·로그·백업·복구",
            "내 전략을 계속 고치고 운영하는 방법",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)
        for stale in ("말한다", "맡긴다", "확인한다", "이어 간다"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, slide)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        title = next(item["title"] for item in rows if item["id"] == "P4-S02")
        self.assertEqual(
            "수업이 끝나면 내 전략으로 내 컴퓨터에서 시스템을 계속 키워 갑니다",
            title,
        )

    def test_part_four_third_slide_frames_intent_critique_and_better_delegation(self):
        slide = self._slide("P4-S03")
        for phrase in (
            "파트 4의 진짜 목표",
            "이것까지 돼?",
            "실현지각력",
            "준비한 프롬프트를 수업 안에 다 끝내지 못할 수도 있습니다",
            "그래도 괜찮습니다",
            "다시 물어본 경험을 더 중요하게 봅니다",
            "의지를 꺼낸다",
            "부딪혀 본다",
            "답을 곱씹는다",
            "내가 병목일 수 있겠구나",
            "더 이해하기 쉽게 일을 맡깁니다",
            "비판적으로 읽은 뒤",
            "part4-spatial-realization-cartoon.png",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)

        self.assertTrue(
            (DECK_ROOT / "assets" / "part4-spatial-realization-cartoon.png").is_file()
        )

        for phrase in (
            "준비한 프롬프트를 수업 안에 다 끝내지 못할 수도 있습니다",
            "몇 개를 끝냈는지보다",
            "다시 물어본 경험을 더 중요하게 보겠습니다",
            "내 생각대로 됐나? 논리는 맞나?",
            "내가 병목일 수도 있겠구나",
            "일을 맡기는 방법까지 스스로 다듬어",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.instructor_script)

    def test_slide_seventeen_uses_the_instructors_real_dialogue_before_prompt_theory(self):
        slide = self._slide("P4-S17")
        for phrase in (
            "강사의 실제 대화",
            "실전에서는 이렇게 대화를 이어 갑니다",
            "처음부터 이론대로 말하지는 않습니다",
            "답을 그대로 믿지 않습니다",
            "복잡하면 다시 줄입니다",
            "이미 이렇게 대화하고 계신가요?",
            "다음 장부터 이 대화를 더 잘 만드는 여섯 가지",
            "part4-real-chat-dialogue.png",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)

        self.assertTrue(
            (DECK_ROOT / "assets" / "part4-real-chat-dialogue.png").is_file()
        )
        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        row = next(item for item in rows if item["id"] == "P4-S17")
        self.assertIsNone(row["promptId"])
        self.assertIn("제가 실제 시스템을 고치면서", self.instructor_script)
        self.assertIn("틀린 방식이라는 뜻은 아닙니다", self.instructor_script)

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
        overview = self._slide("P4-S06")
        for phrase in (
            "전체 실행 지도",
            "한 번 실행하면",
            "후보 목록",
            "분석 보고서",
            "진입 시나리오",
            "매매 결과",
            "DB 기록",
        ):
            with self.subTest(slide="P4-S06", phrase=phrase):
                self.assertIn(phrase, overview)

        directory = self._slide("P4-S07")
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
            with self.subTest(slide="P4-S07", phrase=phrase):
                self.assertIn(phrase, directory)

        entry = self._slide("P4-S08")
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
            with self.subTest(slide="P4-S08", phrase=phrase):
                self.assertIn(phrase, entry)

        function = self._slide("P4-S09")
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
            with self.subTest(slide="P4-S09", phrase=phrase):
                self.assertIn(phrase, function)

        connection = self._slide("P4-S10")
        for phrase in (
            "screening",
            "import",
            "run_screening",
            "candidates",
            "return",
            "다음 단계",
        ):
            with self.subTest(slide="P4-S10", phrase=phrase):
                self.assertIn(phrase, connection)

        configuration = self._slide("P4-S11")
        self.assertNotIn("안전 조건", configuration)
        for phrase in ("반드시 지킬 원칙", "실행할 때 고르는 값", "mock", "simulation"):
            self.assertIn(phrase, configuration)

    def test_beginner_foundations_do_not_require_an_ide_for_code_or_settings(self):
        directory = self._slide("P4-S07")
        for phrase in (
            "GitHub·브라우저",
            "10~20줄",
            "입력·반환값",
            "변경 전후",
        ):
            self.assertIn(phrase, directory)

        configuration = self._slide("P4-S11")
        for phrase in (
            ".env.example",
            "기본 텍스트 편집기",
            "직접 입력",
            "준비됨 / 비어 있음 / 형식 오류",
            ".gitignore",
            "로컬 파일 읽기까지 막지는 않습니다",
        ):
            self.assertIn(phrase, configuration)

    def test_toss_component_swap_lab_connects_interface_setup_and_read_only_quote(self):
        slide = self._slide("P4-S11A")
        for phrase in (
            "인터페이스",
            "구현체",
            "BrokerAdapter",
            "BrokerOrder",
            "BrokerQuote",
            "trading.py",
            "brokers/kis.py",
            "brokers/toss.py",
            "005930",
            "주문 0회",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        row = next(item for item in rows if item["id"] == "P4-S11A")
        self.assertEqual("P4-TOSS", row["promptId"])
        self.assertIn('data-slide-id="P4-S11A"', self.assembled)

        toss_prompt = self.prompts.split("## P4-01", 1)[0]
        for phrase in (
            "## P4-TOSS",
            "P4-TOSS-SETUP",
            "P4-TOSS-RUN",
            "tossctl",
            "공식 Open API",
            "tossctl 0.43.1",
            "openapi status",
            "quote get",
            "토스 계좌와 Open API 키가 없으면",
            "계좌 없음",
            "키를 채팅에 붙여넣거나 에이전트에게 전달하지 마",
            "내 개인 터미널에 직접 입력",
            "주문·취소·정정·잔고·계좌 API 호출은 0회",
            "확인 필요",
        ):
            with self.subTest(prompt_phrase=phrase):
                self.assertIn(phrase, toss_prompt)

        for phrase in (
            "강사 선택 시연 P4-TOSS",
            "인터페이스",
            "구현체",
            "P4-TOSS-SETUP",
            "P4-TOSS-RUN",
            "주문·취소·정정·잔고·계좌 API 호출은 0회",
        ):
            with self.subTest(instructor_phrase=phrase):
                self.assertIn(phrase, self.instructor_script)

    def test_read_only_kis_setup_uses_only_env_credentials_and_redacted_status(self):
        kis_prompt = self.prompts.split("## P4-01", 1)[0].split("## P4-KIS", 1)[1]
        for phrase in (
            "P4-KIS 준비 프롬프트",
            ".env.example",
            "운영체제의 기본 텍스트 편집기",
            "App Key와 App Secret",
            "LECTURE_KIS_MODE",
            "paper면 demo, real이면 real",
            "계좌번호와 HTS ID는 필요하지",
            "이 수급 조회에는 계좌번호와 HTS ID가 필요하지",
            "준비됨 / 비어 있음 / 형식 오류",
            "값 자체를 출력하지",
            ".gitignore",
        ):
            self.assertIn(phrase, kis_prompt)

        self.assertNotIn("kis_devlp.yaml", kis_prompt)
        self.assertNotIn("kis_devlp.yaml", self.instructor_script)
        self.assertIn("KIS 실제 수급", self.instructor_script)

    def test_kis_setup_opens_existing_env_and_copies_template_only_when_missing(self):
        kis_prompt = self.prompts.split("## P4-01", 1)[0].split("## P4-KIS", 1)[1]

        for phrase in (
            "프로젝트 루트의 `.env`가 있는지 먼저 확인",
            "이미 있으면 바로 기본 텍스트 편집기로 열어",
            "없을 때만 `.env.example`을 복사한 뒤",
        ):
            self.assertIn(phrase, kis_prompt)
        self.assertNotIn(
            "`.env.example`을 `.env`로 복사해 프로젝트 폴더 바로 안에 두고",
            kis_prompt,
        )

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

    def test_p4_04_to_p4_08_tells_students_exactly_which_prompt_to_copy_next(self):
        p4_04 = self.prompts.split("## P4-04", 1)[1].split("## P4-05", 1)[0]
        for phrase in (
            "지금 할 프롬프트:",
            "다음에 붙여넣을 프롬프트:",
            "A → P4-05",
            "B → P4-06",
            "C → P4-07",
            "D → P4-08",
            "없음",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, p4_04)

        for prompt_id in ("P4-05", "P4-06", "P4-07", "P4-08"):
            start = self.prompts.index(f"## {prompt_id}")
            next_marker = "---"
            end = self.prompts.find(next_marker, start)
            section = self.prompts[start:end if end != -1 else None]
            self.assertIn(
                f"P4-04 결과에서 지금 할 프롬프트가 {prompt_id}일 때만",
                section,
            )
            self.assertIn("다음에 붙여넣을 프롬프트", section)
            self.assertNotIn("회귀 사례", section)

    def test_strategy_slides_separate_student_copy_flow_from_instructor_demo(self):
        for slide_id, phrases in {
            "P4-S25": ("지금 할 프롬프트", "다음에 붙여넣을 프롬프트"),
            "P4-S26": ("A → P4-05", "B → P4-06", "C → P4-07", "D → P4-08"),
            "P4-S27": ("P4-04", "한 번호만", "P4-05~P4-08", "다음에 붙여넣을 프롬프트"),
            "P4-S28": ("바꾸기 전 미리 보는 예시", "연습 데이터로 결과 확인", "바꾸기 전후 비교"),
            "P4-S30": (
                "실제 PRISM 구독자분의 질문을 추려온 사례입니다.",
                "터틀 추세추종을 간단히 구현하고 나중에 변형할 수 있나요?",
                "ATR로 손절과 비중을 정할 수 있나요?",
                "KOSPI 시황을 보고 장이 나쁘면 줄이고, 좋으면 더 살 수 있나요?",
                "공시도 같이 판단할 수 있나요?",
                "D1~D4로 나눠 차례로 확인합니다.",
            ),
        }.items():
            slide = self._slide(slide_id)
            for phrase in phrases:
                with self.subTest(slide=slide_id, phrase=phrase):
                    self.assertIn(phrase, slide)

        instructor_slides = "".join(
            self._slide(slide_id)
            for slide_id in ("P4-S29", "P4-S30", "P4-S31", "P4-S32")
        )
        self.assertIn("강사 시연", instructor_slides)
        self.assertIn("수강생은 따라 입력하지 않습니다", instructor_slides)
        self.assertNotIn('class="student-action"', instructor_slides)
        self.assertIn("내 번호로 돌아갑니다", self._slide("P4-S40"))

    def test_agent_slides_distinguish_roles_from_tools_and_show_real_handoffs(self):
        definition = self._slide("P4-S12")
        for phrase in ("AgentSpec", "수급 분석가", "supply_summary", "JSON"):
            with self.subTest(slide="P4-S12", phrase=phrase):
                self.assertIn(phrase, definition)

        tool_call = self._slide("P4-S13")
        for phrase in (
            "evidence",
            "llm_complete",
            "extract_json",
            '{"summary": "..."}',
            "규칙 보고서 폴백",
        ):
            with self.subTest(slide="P4-S13", phrase=phrase):
                self.assertIn(phrase, tool_call)

        handoff = self._slide("P4-S14")
        for phrase in (
            "technical_summary",
            "supply_summary",
            "executive_summary",
            "run_buy_agent",
        ):
            with self.subTest(slide="P4-S14", phrase=phrase):
                self.assertIn(phrase, handoff)

        harness = self._slide("P4-S16")
        for phrase in (
            "MY_STRATEGY.md",
            "lecture-strategy-interviewer",
            "lecture-strategy-implementer",
            "lecture-strategy-verifier",
            "한 파일",
        ):
            with self.subTest(slide="P4-S16", phrase=phrase):
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
        slide = self._slide("P4-S15")

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
        self.assertEqual(52, len(rows))
        row = next(item for item in rows if item["id"] == "P4-S23")
        self.assertIn("명세", row["title"])
        self.assertEqual("P4-03", row["promptId"])

        slide = self._slide("P4-S23")
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
            [f"P4-S{index:02d}" for index in range(1, 12)]
            + ["P4-S11A"]
            + [f"P4-S{index:02d}" for index in range(12, 33)]
            + [f"P4-S{index:02d}" for index in range(40, 59)],
            [row["id"] for row in rows],
        )
        self.assertFalse(
            any("계산은 코드에 맡기고 시장 상황 설명은 AI에게 맡깁니다" in row["title"] for row in rows)
        )

        practice = next(row for row in rows if row["id"] == "P4-S27")
        evidence = next(row for row in rows if row["id"] == "P4-S28")
        demo_close = next(row for row in rows if row["id"] == "P4-S40")
        self.assertIn("한 번호만 복사", practice["title"])
        self.assertEqual("P4-05~P4-08", practice["promptId"])
        self.assertIn("어려운 말", evidence["title"])
        self.assertEqual("P4-05~P4-08", evidence["promptId"])
        self.assertEqual("P4-05~P4-08", demo_close["promptId"])

        for phrase in (
            "P4-D1.md의 수정 전후 결과 표",
            "P4-D2.md의 입력 확인 표",
            "P4-D3.md의 market_condition 경로 표",
            "P4-D4.md에는 `사용 경로 / 수집 건수",
            "완료 / 폴백으로 검증 / 다음 작업",
            "수강생은 따라 입력하지 않습니다",
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

    def test_direct_rerun_after_practice_supports_selected_profiles_without_scheduling(self):
        slide = self._slide("P4-S52")
        for phrase in (
            "계속 수정하고 싶으신 경우",
            "예약을 새로 걸지 않고",
            "main.py",
            "mock·simulation",
            "real_data·simulation",
            "research·simulation",
            "paper",
            "live",
            "한 규칙씩 반복",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, slide)

        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        rerun = next(item for item in rows if item["id"] == "P4-S52")
        self.assertEqual("P4-14", rerun["promptId"])
        prompt = self.prompts.split("## P4-14", 1)[1].split("## P4-15", 1)[0]
        for phrase in (
            "main.py",
            "예약·스케줄러·서비스 등록은 사용하지 말고",
            "P4-04의 실행 결과와 현재 트랙 계획이 남아 있으면 참고",
            "P4-04 계획 없음",
            "추정",
            "real_data",
            "research",
            "paper",
            "live",
            "자동으로 여러 번 반복하지 마",
            "수정한 파일과 규칙",
        ):
            with self.subTest(prompt=phrase):
                self.assertIn(phrase, prompt)
        self.assertIn("P4-14", self.instructor_script)

    def test_prompt_sequence_separates_mock_practice_schedule_from_optional_direct_rerun(self):
        before_direct_rerun = self.prompts.split("## P4-14", 1)[0]
        for phrase in (
            "기본 트랙 실습과 예약 실습(P4-05~P4-13)",
            "API 키 없는 mock·simulation",
            "다른 프로필은 P4-14에서 직접 다시 실행할 때만 선택",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, before_direct_rerun)
        self.assertNotIn("선택한 실행 프로필의 전체 실행", before_direct_rerun)

        schedule = self.prompts.split("## P4-11", 1)[1].split("## P4-14", 1)[0]
        for phrase in (
            "이 예약 실습은 반드시 mock·simulation",
            "실데이터·리서치·모의투자는 이 예약에 섞지 마",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, schedule)

        direct = self.prompts.split("## P4-14", 1)[1].split("## P4-13", 1)[0]
        for phrase in (
            "P4-11~P4-13의 예약 실습과 별도로 진행합니다",
            "LECTURE_PROFILE=paper` + `LECTURE_TRADE_MODE=demo",
            "`classroom`과 `backtest`는",
            "이 대괄호 안의 값은 내가 이번 실행에서 직접 고르는 값",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, direct)

    def test_every_student_prompt_starts_with_its_current_index(self):
        blocks = re.findall(r"```text\n(.*?)\n```", self.prompts, flags=re.DOTALL)
        expected_ids = [
            "P4-00",
            "P4-KIS-SETUP",
            "P4-KIS-RUN",
            "P4-TOSS-SETUP",
            "P4-TOSS-RUN",
            "P4-01",
            "P4-02",
            "P4-03",
            "P4-04",
            "P4-05",
            "P4-06",
            "P4-07",
            "P4-08",
            "P4-09",
            "P4-10",
            "P4-11",
            "P4-12",
            "P4-14",
            "P4-13",
            "P4-15",
            "P4-16",
        ]
        self.assertEqual(expected_ids, [
            block.splitlines()[0].split(":", 1)[1].split("·", 1)[0].strip()
            for block in blocks
        ])
        for block in blocks:
            self.assertRegex(
                block.splitlines()[0],
                r"^\[현재 프롬프트: [^\]]+ · .+\]$",
            )

    def test_external_evidence_is_filtered_before_llm_input_and_close_points_to_a_new_system(self):
        quality_flow = self._slide("P4-S32")
        for phrase in (
            "DART RSS",
            "최대 3건",
            "통신 오류 문구",
            "수집 건수",
            "포함 / 제외 / 검토 필요",
            "LLM에 넘긴 자료",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, quality_flow + self.instructor_script)

        close = self._slide("P4-S58")
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
        closing_row = next(item for item in rows if item["id"] == "P4-S58")
        self.assertIn("여러분만의 전략과 시스템", closing_row["title"])

    def test_after_class_cloud_operations_are_a_three_slide_roadmap_not_a_telegram_feature(self):
        rows = [
            item
            for module in self.manifest["decks"]["part4"]["modules"]
            for item in module["slides"]
        ]
        by_id = {row["id"]: row for row in rows}

        self.assertEqual("P4-16", by_id["P4-S57"]["promptId"])
        self.assertIsNone(by_id["P4-S55"]["promptId"])
        self.assertIsNone(by_id["P4-S56"]["promptId"])
        roadmap = self._slide("P4-S55")
        self.assertIn("after-class-cloud-operations-roadmap.png", roadmap)
        for phrase in (
            "Git은 GitHub와 다릅니다",
            "코드의 변경 기록",
            "무엇이 바뀌었는지 비교",
            "문제가 생기기 전 상태로 되돌릴",
            "수업 뒤에 따로 공부",
            "commit",
            "diff",
            "branch",
            "restore",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, roadmap)
        self.assertIn("## P4-16", self.prompts)
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
            "재현용 fixture",
            "dart-samsung-company-rss.xml",
            "자동 재시도",
        ):
            self.assertIn(phrase, d4)
        self.assertNotIn("OpenDART API를 연결", d4)

    def test_d4_uses_a_fixed_company_feed_and_parseable_fixture_without_preclass_blanks(self):
        start = self.instructor_script.index("P4-D1~P4-D4 · 강사 통합 시연")
        end = self.instructor_script.index("**이 구간의 완료 기준:**", start)
        block = self.instructor_script[start:end]

        self.assertIn("삼성전자 005930", block)
        self.assertIn(
            "https://dart.fss.or.kr/api/companyRSS.xml?crpCd=00126380",
            block,
        )
        self.assertIn("lecture/fixtures/dart-samsung-company-rss.xml", block)
        self.assertIn("포함 / 제외 / 검토 필요", block)
        self.assertIn("추가 데이터 소스", block)
        self.assertNotIn("[수업 직전 복사한 URL]", block)
        self.assertNotIn("[한 문장]", block)
        self.assertNotIn("수업 전 1분 준비", block)

        fixture = ROOT / "lecture" / "fixtures" / "dart-samsung-company-rss.xml"
        root = ET.parse(fixture).getroot()
        items = root.findall("./channel/item")
        self.assertEqual(3, len(items))
        self.assertEqual(
            "DART : (유가)삼성전자의 공시",
            root.findtext("./channel/title"),
        )
        for item in items:
            self.assertTrue(item.findtext("title"))
            self.assertRegex(item.findtext("link", ""), r"rcpNo=\d{14}$")
            self.assertTrue(item.findtext("pubDate"))

    def test_student_tracks_reuse_my_strategy_and_harness_without_placeholder_strategy(self):
        start = self.prompts.index("## P4-04")
        end = self.prompts.index("## P4-09", start)
        block = self.prompts[start:end]
        for phrase in (
            "MY_STRATEGY.md",
            "지금 할 프롬프트",
            "다음에 붙여넣을 프롬프트",
            "연습 데이터 전체 실행",
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

    def test_prompt_guides_appear_only_when_a_specific_prompt_is_available(self):
        expected_prompt_ids = {
            slide["id"]: slide["promptId"]
            for module in self.manifest["decks"]["part4"]["modules"]
            for slide in module["slides"]
        }
        instructor_ids = {
            slide["id"]
            for module in self.manifest["decks"]["part4"]["modules"]
            for slide in module["slides"]
            if slide.get("guideAudience") == "instructor"
        }
        slides = re.findall(
            r'<section data-slide-id="([^"]+)"[^>]*class="slide[^>]*>(.*?)</section>',
            self.assembled,
            flags=re.S,
        )

        self.assertGreater(len(slides), 40)
        self.assertNotIn("지금은 개념을 확인합니다", self.assembled)
        for slide_id, slide in slides:
            with self.subTest(slide=slide_id):
                if expected_prompt_ids[slide_id]:
                    self.assertIn('class="prompt-guide"', slide)
                    audience = "강사 자료" if slide_id in instructor_ids else "수강생 자료"
                    self.assertIn(audience, slide)
                else:
                    self.assertNotIn('class="prompt-guide"', slide)

    def test_instructor_demo_prompt_guides_do_not_point_to_student_materials(self):
        prompt_id = "P4-D1~P4-D4"
        self.assertIn(f"강사 자료 → {prompt_id}", self.assembled)
        self.assertNotIn(f"수강생 자료 → {prompt_id}", self.assembled)
        self.assertIn(prompt_id, self.instructor_script)
        self.assertNotIn(prompt_id, self.prompts)

    def test_practice_slides_keep_instructor_demo_separate_from_student_actions(self):
        instructor_demo = "".join(
            self._slide(slide_id)
            for slide_id in ("P4-S29", "P4-S30", "P4-S31", "P4-S32")
        )
        self.assertNotIn('class="student-action"', instructor_demo)
        for phrase in (
            "지금 할 프롬프트",
            "한 번호만 복사",
            "강사 사례",
            "수강생은 따라 입력하지 않습니다",
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
