import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDENT_PROMPTS = (
    ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md"
)
PART3_SOURCE = ROOT / "강의자료" / "deck-src" / "part3"
INSTRUCTOR_SCRIPT = ROOT / "강의자료" / "강사용_실습진행_스크립트.md"
START_GUIDE = ROOT / "강의자료" / "수업_시작_전_안내.md"


APPLICATION_QUESTIONS = {
    "P3-M1": (
        "내 전략이라면 후보를 가장 먼저 어떤 조건으로 거를까?",
        "후보가 너무 많다면 무엇을 우선해 순서를 정할까?",
        "screening.py에서 바꿀 한 가지와 그대로 둘 안전장치는 무엇일까?",
    ),
    "P3-M2": (
        "내 전략에서 숫자로 확인할 근거와 맥락으로 읽을 근거는 각각 무엇일까?",
        "내가 아는 데이터 출처에서 어떤 값만 골라 어느 분석가에게 줄까?",
        "어떤 근거가 빠지면 매수 판단을 다음 단계로 넘기지 않을까?",
    ),
    "P3-M3": (
        "AI가 좋다고 해도 코드가 반드시 막아야 할 진입은 무엇일까?",
        "내 전략에서는 손절·수익 보호·목표가를 어떤 순서로 확인할까?",
        "체결 상태가 불분명할 때 새 주문 전에 무엇을 확인할까?",
    ),
    "P3-M4": (
        "거래가 끝나면 처음 계획과 실제 결과 중 무엇을 비교해 남길까?",
        "같은 실수가 몇 번 반복되면 장기 원칙으로 만들까?",
        "오늘의 교훈 중 다음 거래에는 넣지 말아야 할 일회성 상황은 무엇일까?",
    ),
    "P3-M5": (
        "내 컴퓨터는 지금 어느 운영 단계까지 안전하게 갈 수 있을까?",
        "service manager가 대신 지켜야 할 일은 무엇일까?",
        "브로커 준비 상태가 CONDITIONAL이면 다음 행동은 무엇일까?",
    ),
}


PROMPT_SLIDES = {
    "P3-M1": "P3-S14",
    "P3-M2": "P3-S21",
    "P3-M3": "P3-S32",
    "P3-M4": "P3-S38",
    "P3-M5": "P3-S41",
}


def _markdown_block(source: str, prompt_id: str) -> str:
    match = re.search(
        rf"^## {re.escape(prompt_id)}\b.*?(?=^## |\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing prompt block: {prompt_id}")
    return match.group(0)


def _slide(source: str, slide_id: str) -> str:
    match = re.search(
        rf"<!-- {re.escape(slide_id)}\b.*?<section\b.*?</section>",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing {slide_id}")
    return match.group(0)


class Part3StudentLearningContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompts = STUDENT_PROMPTS.read_text(encoding="utf-8")
        cls.slides = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(PART3_SOURCE.glob("*.html"))
        )
        cls.instructor = INSTRUCTOR_SCRIPT.read_text(encoding="utf-8")
        cls.start_guide = START_GUIDE.read_text(encoding="utf-8")

    def test_student_module_prompts_use_only_the_course_repository(self):
        forbidden = (
            "PIPELINE_ARCHITECTURE_ko.md",
            "원본 PRISM",
            "trigger_batch.py",
            "prism-us/",
            "cores/oneil_fallback.py",
            "tracking/compression.py",
        )
        for prompt_id in ("P3-M1", "P3-M2", "P3-M3", "P3-M4", "P3-M5"):
            block = _markdown_block(self.prompts, prompt_id)
            for phrase in forbidden:
                self.assertNotIn(phrase, block, f"{prompt_id}: {phrase}")

    def test_every_module_ends_with_unanswered_strategy_application_questions(self):
        for prompt_id, questions in APPLICATION_QUESTIONS.items():
            block = _markdown_block(self.prompts, prompt_id)
            slide = _slide(self.slides, PROMPT_SLIDES[prompt_id])
            slide_text = re.sub(r"<[^>]+>", "", slide)

            self.assertIn(
                "마지막에는 내가 직접 답할 아래 질문 세 개를 질문만 남겨줘",
                block,
                prompt_id,
            )
            self.assertIn("답을 대신 쓰지 마", block, prompt_id)
            self.assertIn("내 전략에 대입", slide_text, prompt_id)
            for question in questions:
                self.assertIn(question, block, f"{prompt_id} prompt")
                self.assertIn(question, slide_text, f"{prompt_id} slide")

    def test_instructor_uses_varied_learner_actions_for_each_module(self):
        for question in (
            "어제는 강세장, 오늘은 약세장입니다. 후보를 같은 기준으로 골라도 될까요?",
            "이 종목을 사기 전에, 어떤 정보까지 확인하고 싶으세요?",
            "AI가 매수를 추천했습니다. 이 의견만 믿고 주문해도 될까요?",
            "어제 손절한 종목이 오늘 다시 떴습니다. 다시 사도 될까요?",
        ):
            self.assertIn(question, self.instructor)

        self.assertGreaterEqual(self.instructor.count("20초 예상"), 4)
        for learner_action in (
            "60초 짝 대화",
            "정보 세 가지",
            "A/B 투표",
            "바로 다시 산다 / 하루 더 본다 / 조건을 다시 확인한다",
            "내 안전선 한 문장",
        ):
            self.assertIn(learner_action, self.instructor)
        self.assertNotIn("안전문", self.instructor)

    def test_instructor_has_project_answer_anchors_after_pair_talk(self):
        self.assertEqual(
            self.instructor.count("**수강생 판단 뒤 lecture-prism 기준선**"),
            5,
        )
        for answer_anchor in (
            "거래량 5배·시가총액 5,000억·상승 여부",
            "등락률이 높은 순서로 최대 세 종목",
            "그 섹션만 규칙 보고서로 바뀝니다",
            "목표가 > 현재가 > 손절가",
            "손익비 1.5 이상",
            "손절 → 트레일링 스탑 → 목표가",
            "7일이 지나면 중기",
            "30일이 지난 중기 교훈",
            "두 번 이상 반복",
            "장기 원칙은 최대 20개",
            "실제 수익률과 청산 사유까지 깊게 비교하지는 않습니다",
            "다음 날 자동으로 매수를 막는 규칙은 아직 없습니다",
            "main.py를 켜 둔다고 운영이 되는 것은 아닙니다",
            "전체 배치, 보유 감시, 주문 대사, 기억 압축, 상태·알림",
            "doctor → simulation → paper → live",
            "KIS는 기준선",
            "Kiwoom은 조건부",
            "Toss는 공식 Open API와 WTS를 분리",
        ):
            self.assertIn(answer_anchor, self.instructor)

    def test_module_five_prompts_are_read_only_and_choose_a_stage_without_side_effects(self):
        module_five = _markdown_block(self.prompts, "P3-M5")

        for phrase in (
            "읽기 전용 운영 준비 감사",
            "목표 운영 단계 계획",
            "mock",
            "real_data",
            "research",
            "paper",
            "live",
            "configured / missing",
            "시크릿 값은 출력하지 마",
            "서비스 등록을 하지 마",
            "플래그 값을 바꾸지 마",
            "실제 주문·취소를 실행하지 마",
            "LECTURE_ENABLE_LIVE_BROKER",
            "LECTURE_ALLOW_REAL_BROKER",
            "doctor → simulation → paper → live",
            "operations.py doctor",
            "operations.py status",
            "operations.py schedule",
            "service manager",
            "main.py를 터미널에 계속 띄워 두는 방식",
            "KIS",
            "Kiwoom",
            "Toss 공식 Open API",
            "WTS",
        ):
            self.assertIn(phrase, module_five, phrase)

        code_blocks = re.findall(r"```text\n(.*?)```", module_five, flags=re.DOTALL)
        self.assertGreaterEqual(len(code_blocks), 2)
        for block in code_blocks[:2]:
            with self.subTest(block=block[:40]):
                self.assertIn("시크릿 값은 출력하지 마", block)
                self.assertIn("서비스 등록을 하지 마", block)
                self.assertIn("플래그 값을 바꾸지 마", block)
                self.assertIn("실제 주문·취소를 실행하지 마", block)
                self.assertIn("configured / missing", block)

    def test_module_five_operations_boundaries_are_synced_across_script_and_slides(self):
        module_five = _markdown_block(self.prompts, "P3-M5")
        slide_40 = _slide(self.slides, "P3-S40")
        slide_41 = _slide(self.slides, "P3-S41")
        combined_slides = re.sub(r"<[^>]+>", "", slide_40 + "\n" + slide_41)

        for source in (module_five, self.instructor):
            for phrase in (
                "mock",
                "real_data",
                "research",
                "paper",
                "live",
                "doctor → simulation → paper → live",
                "service manager",
                "operations.py schedule",
                "LECTURE_ENABLE_LIVE_BROKER",
                "LECTURE_ALLOW_REAL_BROKER",
                "KIS",
                "Kiwoom",
                "Toss",
            ):
                self.assertIn(phrase, source, phrase)

        for phrase in (
            "연습 데이터",
            "실데이터",
            "모의투자",
            "실거래",
            "준비 상태 점검",
            "준비됨",
            "준비 안 됨",
        ):
            self.assertIn(phrase, combined_slides, phrase)

        for source in (module_five, self.instructor):
            for phrase in (
                "준비 상태 점검(doctor)",
                "서비스 관리자(service manager)",
                "준비됨(configured)",
                "준비 안 됨(missing)",
                "코딩 에이전트",
            ):
                self.assertIn(phrase, source, phrase)

        for phrase in (
            "무엇을 실행하나요?",
            "operations.py doctor",
            "operations.py status",
            "수강생이 터미널 명령어를 직접 입력하지 않습니다",
        ):
            self.assertIn(phrase, module_five, phrase)

        for phrase in (
            "main.py를 켜 둔다고 운영이 되는 것은 아닙니다",
            "전체 배치",
            "보유 감시",
            "주문 대사",
            "기억 압축",
            "상태·알림",
            "공식 Open API",
            "WTS",
        ):
            self.assertIn(phrase, self.instructor, phrase)

    def test_dashboard_prompt_instructor_and_slide_share_the_same_safe_fallback(self):
        dashboard_prompt = _markdown_block(self.prompts, "P3-05")
        dashboard_slide = _slide(self.slides, "P3-S42")
        for phrase in ("매매현황", "AI 분석 근거", "축적된 피드백"):
            self.assertIn(phrase, dashboard_prompt)
            self.assertIn(phrase, self.instructor)
            self.assertIn(phrase, dashboard_slide)
        for phrase in ("준비된 캡처", "기본 연습 데이터 파이프라인 성공과는 별개"):
            self.assertIn(phrase, dashboard_prompt)
            self.assertIn(phrase, self.instructor)

    def test_first_run_supports_real_data_discord_and_mock_fallback_lanes(self):
        for phrase in (
            "실데이터와 Discord까지 포함해 전체 흐름",
            "연습 데이터(기술 이름: mock)",
            "실데이터(real_data)",
            "Discord 판단 알림",
            "실데이터(yfinance)",
            "LECTURE_PROFILE=mock",
            "LECTURE_NOTIFY_DISCORD=0",
        ):
            self.assertIn(phrase, self.prompts, phrase)

        for phrase in (
            "real_data + Discord + simulation",
            "준비되지 않은 수강생은 Discord 없이 연습 데이터로 진행한다",
            "준비되지 않았거나 연결에 실패한 사람은 연습 데이터로 자동 전환합니다",
            "실데이터·Discord 전체 실행 로그",
        ):
            self.assertIn(phrase, self.instructor, phrase)

        first_run = _slide(self.slides, "P3-S05")
        self.assertIn("실데이터·Discord까지 보고", first_run)
        self.assertIn("아니면 연습 데이터로 같은 흐름", first_run)
        self.assertIn("연습 데이터 또는 준비된 실데이터", first_run)

    def test_first_run_prepares_discord_and_names_each_saved_evidence_path(self):
        for source in (self.prompts, self.instructor):
            for phrase in (
                "Discord를 보여 줄 사람만 P3-01 전에",
                "LECTURE_NOTIFY_DISCORD=1",
                "DISCORD_WEBHOOK_URL",
                "코딩 에이전트의 실행 출력",
                "`logs/`",
                "`reports/`",
                "`prism.db`",
                "피드백 저장 알림",
            ):
                self.assertIn(phrase, source, phrase)

        self.assertIn(
            "웹후크 주소는 코딩 에이전트 채팅에 붙여넣지 않는다",
            self.instructor,
        )

        first_run = _markdown_block(self.prompts, "P3-01")
        for phrase in (
            "Discord 선택 준비 프롬프트",
            'DISCORD_WEBHOOK_URL=""',
            "내가 `.env` 파일을 직접 열어 URL만 넣고 저장할 수 있게",
            "웹후크 주소를 이 채팅에 붙여넣으라고 요구하지 마",
            "웹후크 주소는 코딩 에이전트 채팅에 붙여넣지 마세요",
            "실제 주문·브로커·계좌·main.py 실행은 하지 마",
        ):
            self.assertIn(phrase, first_run, phrase)

    def test_student_copy_uses_practice_data_before_the_mock_technical_name(self):
        first_run = _markdown_block(self.prompts, "P3-01")

        self.assertIn("연습 데이터와 가상 체결", first_run)
        self.assertIn("연습 데이터(mock) 경로", first_run)
        self.assertIn("연습 데이터로 돌아간 이유", first_run)
        self.assertNotIn("mock + simulation", first_run)
        self.assertNotIn("mock으로 돌아간 이유", first_run)

    def test_module_two_saves_a_readable_analysis_report(self):
        module_two = _markdown_block(self.prompts, "P3-M2")
        slide = _slide(self.slides, "P3-S21")

        for source in (module_two, self.instructor):
            self.assertIn("`reports/`", source)
            self.assertIn("Markdown 분석 보고서", source)
        self.assertIn("보고서 파일 경로", module_two)
        slide_text = re.sub(r"<[^>]+>", "", slide)
        self.assertIn("reports/에 남습니다", slide_text)
        self.assertIn("매수 의견·점수·목표가·손절가가 없는", module_two)

    def test_module_two_opens_a_substantial_report_even_without_llm(self):
        module_two = _markdown_block(self.prompts, "P3-M2")
        slide_text = re.sub(r"<[^>]+>", "", _slide(self.slides, "P3-S21"))

        for phrase in (
            "LLM이 연결되지 않아도",
            "한눈에 보는 데이터",
            "우호적 근거·경계할 근거·다음 확인",
            "핵심 수치·전문 분석가 해석·데이터 한계·확인할 사항",
        ):
            self.assertIn(phrase, module_two, phrase)
            self.assertIn(phrase, self.instructor, phrase)
        self.assertIn("LLM 없이도 읽을 만한 보고서", slide_text)

    def test_module_two_treats_yfinance_news_as_unverified_headlines(self):
        module_two = _markdown_block(self.prompts, "P3-M2")

        for phrase in (
            "종목 직접 관련 뉴스·주변 산업 뉴스·관련성 불명",
            "기사 본문을 실제로 열어 읽지 않았다면",
            "호재·악재나 실적 영향을 단정하지 마",
            "관련성 확인 필요",
        ):
            self.assertIn(phrase, module_two, phrase)
            self.assertIn(phrase, self.instructor, phrase)

    def test_module_two_turns_data_limits_into_a_section_level_design(self):
        module_two = _markdown_block(self.prompts, "P3-M2")
        data_slide = _slide(self.slides, "P3-S22")

        for phrase in (
            "데이터 한계",
            "담당 섹션",
            "알맞은 출처의 종류",
            "가져올 필드",
            "기준 시각·단위·갱신 주기",
            "연결할 코드 위치",
            "실패하면 할 일",
        ):
            self.assertIn(phrase, module_two, phrase)

        for phrase in (
            "yfinance 한 곳",
            "수급은 거래량 간접 지표",
            "기사 본문이 아니라 제목",
            "공시 사이트, 거래소 자료, 증권사 HTS·MTS, 기업 IR, 뉴스 원문, 거시경제 통계",
            "출처·기준 시각·단위·갱신 주기·실패 시 동작",
        ):
            self.assertIn(phrase, self.instructor, phrase)

        slide_text = re.sub(r"<[^>]+>", "", data_slide)
        self.assertIn("더 좋은 LLM이 아니라 알맞은 데이터", slide_text)
        self.assertIn("달라진 판단 확인", slide_text)

    def test_module_two_prefers_one_real_data_report_but_keeps_a_fallback(self):
        module_one = _markdown_block(self.prompts, "P3-M1")
        module_two = _markdown_block(self.prompts, "P3-M2")
        slide = _slide(self.slides, "P3-S21")
        slide_text = re.sub(r"<[^>]+>", "", slide)

        for phrase in (
            "Yahoo Finance",
            "LECTURE_PROFILE=real_data",
            "analysis.py 005930",
            "한 종목을 한 번 실행",
            "자동으로 다시 시도하지 마",
            "연습 데이터로 돌아가",
        ):
            self.assertIn(phrase, module_two, phrase)
        self.assertIn("실데이터를 한 번 읽고", slide_text)
        self.assertIn("실데이터를 한 번 확인", self.instructor)
        self.assertIn("`--real`은 실행하지 마", module_one)

    def test_start_guide_selects_workspace_before_repository_setup_chat(self):
        for phrase in (
            "빈 폴더 하나",
            "작업 공간·프로젝트 폴더로 먼저 선택",
            "이미 시작한 코딩 에이전트의 채팅창",
            "현재 작업 공간에 공개 GitHub 저장소",
        ):
            self.assertIn(phrase, self.start_guide, phrase)
        self.assertNotIn("Codex 또는 Claude Code에서 열어줘", self.start_guide)
        self.assertIn("현재 작업 공간의 실제 경로", self.start_guide)

    def test_start_guide_prepares_shared_venv_with_declared_dependencies(self):
        for phrase in (
            "강사와 수강생 모두가 합니다",
            "설치되어 있는 Python 중 3.10 이상",
            "프로젝트 루트의 `.venv`에 `requirements.txt` 전체를 설치",
            "전역 Python이나 전역 pip에는 설치하지 마",
            "기본 mock 수업은 패키지 설치 실패와 별개로 계속할 수",
            "실데이터·Discord·OAuth·브로커가 자동으로 켜지는 것은 아닙니다",
        ):
            self.assertIn(phrase, self.start_guide, phrase)
        self.assertNotIn("requirements.txt에서 `yfinance`만 설치해줘", self.start_guide)

    def test_real_data_first_run_uses_scoped_network_and_one_ticker(self):
        for phrase in (
            "범위 제한 네트워크 승인",
            "005930 한 종목",
            "자동으로 다시 시도하지 마",
            "네트워크 권한 미승인",
            "Yahoo 429",
            "Discord 실제 전송 성공 건수",
            "P3-01에서 실데이터가 확인됐으면 새 조회를 하지 말고",
        ):
            self.assertIn(phrase, self.prompts, phrase)

        for phrase in (
            "범위 제한 네트워크 승인",
            "005930 한 종목",
            "실제 전송 성공 건수",
            "Yahoo 429",
            "전역 샌드박스를 끄거나 권한을 통째로 우회하지 마",
        ):
            self.assertIn(phrase, self.instructor, phrase)

        for phrase in (
            "범위 제한 네트워크 승인을 요청",
            "전역 권한 우회나 시스템 설정 변경은 하지 마",
        ):
            self.assertIn(phrase, self.start_guide, phrase)

        for source in (self.prompts, self.instructor, self.start_guide):
            self.assertNotIn("--dangerously-skip-permissions", source)

        first_run = _markdown_block(self.prompts, "P3-01")
        self.assertIn("005930 한 종목", first_run)
        self.assertNotIn("실데이터 스크리닝", first_run)

    def test_instructor_oauth_rehearsal_does_not_duplicate_mock_after_format_fallback(self):
        match = re.search(
            r"^### 리허설 프롬프트 2.*?^```text\n(.*?)^```",
            self.instructor,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        rehearsal = match.group(1)
        self.assertIn("Codex CLI 호출 자체가 실패했을 때만", rehearsal)
        self.assertIn(
            "응답 형식 불일치나 규칙 폴백만으로는 mock을 추가 실행하지 마",
            rehearsal,
        )
        self.assertIn("실데이터 research 결과를 그대로 기록", rehearsal)

    def test_oauth_rehearsal_requests_scoped_external_execution(self):
        match = re.search(
            r"^### 리허설 프롬프트 2.*?^```text\n(.*?)^```",
            self.instructor,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        rehearsal = match.group(1)
        oauth_prompt = _markdown_block(self.prompts, "P3-M2L")
        for source in (rehearsal, oauth_prompt):
            self.assertIn("승인된 외부 실행", source)
            self.assertIn("codex exec", source)
            self.assertIn("전역 샌드박스를 끄거나 권한을 통째로 우회하지 마", source)

    def test_llm_bridge_splits_by_login_readiness_and_rejoins_module_three(self):
        bridge = _markdown_block(self.prompts, "P3-M2L")

        for phrase in (
            "A 경로 · 공식 Codex 로그인이 이미 준비된 사람",
            "B 경로 · 공식 Codex 로그인이 준비되지 않은 사람",
            "OAuth 전체 호출은 한 번만",
            "이번 실행의 OAuth 호출은 0회",
            "실제 LLM 성공이라고 명시된 경우에만",
            "LLM 결과를 꾸며내지 마",
            "P3-M3으로 합류",
            "LECTURE_PROFILE=research",
            "LECTURE_LLM_MODE=oauth",
            "Perplexity·Firecrawl·Discord·브로커",
            "simulation",
            "BUY를 HOLD로만",
            "점수·목표가·손절가는 규칙",
        ):
            self.assertIn(phrase, bridge, phrase)
            self.assertIn(phrase, self.instructor, phrase)

        self.assertNotIn("## P3-05 · 선택: 공식 Codex OAuth research", self.prompts)

    def test_first_screen_labels_saved_oauth_evidence_as_past_work(self):
        match = re.search(
            r"^### 수업 시작 직후 프롬프트.*?^```text\n(.*?)^```",
            self.instructor,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        first_screen = match.group(1)
        for phrase in (
            "수업 전 리허설에서 저장한",
            "이번 실행의 OAuth 호출은 0회",
            "지금 OAuth를 호출한 것은 아닙니다",
        ):
            self.assertIn(phrase, first_screen, phrase)

    def test_slide_13_points_to_the_complete_prompt_block(self):
        slide_13 = _slide(self.slides, "P3-S14")
        self.assertIn("P3-M1 블록 전체", slide_13)
        self.assertIn("프롬프트 파일", slide_13)
        self.assertNotIn("원본 PRISM과 비교", slide_13)
        self.assertNotIn("아래 문장을 코딩 에이전트에게 그대로 붙여넣습니다", slide_13)

    def test_every_module_prompt_slide_uses_the_complete_markdown_block(self):
        expected = {
            "P3-S14": "P3-M1",
            "P3-S21": "P3-M2",
            "P3-S32": "P3-M3",
            "P3-S38": "P3-M4",
            "P3-S41": "P3-M5",
        }
        for slide_id, prompt_id in expected.items():
            slide = _slide(self.slides, slide_id)
            self.assertIn(f"{prompt_id} 블록 전체", slide, slide_id)
            self.assertNotIn(
                "아래 문장을 코딩 에이전트에게 그대로 붙여넣습니다",
                slide,
                slide_id,
            )

    def test_instructor_owns_original_prism_comparison(self):
        self.assertIn(
            "원본 PRISM과의 비교는 강사가 앞선 그림과 비교 슬라이드에서 설명합니다",
            self.instructor,
        )
        self.assertIn(
            "수강생은 원본 저장소를 받거나 대조하지 않습니다",
            self.instructor,
        )

    def test_part_three_language_matches_the_five_stage_pipeline(self):
        self.assertNotIn("분석의 BUY", self.prompts)
        self.assertNotIn("분석의 BUY", self.instructor)
        self.assertNotIn("분석의 BUY", self.slides)
        self.assertNotIn("네 단계", self.instructor)
        self.assertNotIn("네 단계", self.slides)
        self.assertIn("매수 에이전트의 BUY", self.prompts)

    def test_part_three_does_not_preteach_the_part_four_north_star_activity(self):
        self.assertNotIn("북극성", self.prompts)


if __name__ == "__main__":
    unittest.main()
