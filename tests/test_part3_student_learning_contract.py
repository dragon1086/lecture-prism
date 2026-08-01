import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDENT_PROMPTS = (
    ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md"
)
PART3_SOURCE = ROOT / "강의자료" / "deck-src" / "part3"
INSTRUCTOR_SCRIPT = ROOT / "강의자료" / "강사용_실습진행_스크립트.md"


APPLICATION_QUESTIONS = {
    "P3-M1": (
        "내 전략이라면 후보를 가장 먼저 어떤 조건으로 거를까?",
        "후보가 너무 많다면 무엇을 우선해 순서를 정할까?",
        "screening.py에서 바꿀 한 가지와 그대로 둘 안전장치는 무엇일까?",
    ),
    "P3-M2": (
        "내 전략에서 숫자로 확인할 근거와 맥락으로 읽을 근거는 각각 무엇일까?",
        "여섯 역할 중 반드시 남길 분석가와 새로 보태고 싶은 분석가는 무엇일까?",
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
}


PROMPT_SLIDES = {
    "P3-M1": "P3-S13",
    "P3-M2": "P3-S20",
    "P3-M3": "P3-S29",
    "P3-M4": "P3-S36",
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

    def test_student_module_prompts_use_only_the_course_repository(self):
        forbidden = (
            "PIPELINE_ARCHITECTURE_ko.md",
            "원본 PRISM",
            "trigger_batch.py",
            "prism-us/",
            "cores/oneil_fallback.py",
            "tracking/compression.py",
        )
        for prompt_id in ("P3-M1", "P3-M2", "P3-M3", "P3-M4"):
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

    def test_instructor_opens_each_module_with_a_problem_and_keeps_pair_talk(self):
        for question in (
            "시장이 흔들려도 어제와 같은 기준으로 후보를 골라도 될까요?",
            "차트가 좋아 보인다는 이유만으로 종목 분석을 끝내도 될까요?",
            "AI가 BUY 8점을 줬는데 주문이 0건이면 오류일까요?",
            "방금 샀는데 아직 결과도 모르면서 성공 교훈을 만들어도 될까요?",
        ):
            self.assertIn(question, self.instructor)

        self.assertGreaterEqual(self.instructor.count("20초 예상"), 4)
        self.assertGreaterEqual(self.instructor.count("60초 짝 대화"), 4)

    def test_instructor_has_project_answer_anchors_after_pair_talk(self):
        self.assertEqual(
            self.instructor.count("**짝 대화 뒤 lecture-prism 기준선**"),
            4,
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
        ):
            self.assertIn(answer_anchor, self.instructor)

    def test_slide_13_points_to_the_complete_prompt_block(self):
        slide_13 = _slide(self.slides, "P3-S13")
        self.assertIn("P3-M1 블록 전체", slide_13)
        self.assertIn("프롬프트 파일", slide_13)
        self.assertNotIn("원본 PRISM과 비교", slide_13)
        self.assertNotIn("아래 문장을 코딩 에이전트에게 그대로 붙여넣습니다", slide_13)

    def test_every_module_prompt_slide_uses_the_complete_markdown_block(self):
        expected = {
            "P3-S13": "P3-M1",
            "P3-S20": "P3-M2",
            "P3-S29": "P3-M3",
            "P3-S36": "P3-M4",
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
