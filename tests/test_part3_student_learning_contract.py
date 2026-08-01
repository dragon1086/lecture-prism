import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDENT_PROMPTS = (
    ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md"
)
PART3_SOURCE = ROOT / "강의자료" / "deck-src" / "part3"
INSTRUCTOR_SCRIPT = ROOT / "강의자료" / "강사용_실습진행_스크립트.md"


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

    def test_module_one_questions_match_what_students_have_learned(self):
        block = _markdown_block(self.prompts, "P3-M1")

        self.assertNotIn("뒤의 매수 방식과 왜 잘 맞는가", block)
        self.assertNotIn("이미지 생성", block)
        self.assertNotIn("로컬 HTML", block)
        self.assertIn("어떤 조건이 종목을 가장 먼저 걸러냈는가?", block)
        self.assertIn("남은 후보는 어떤 기준으로 순서가 정해졌는가?", block)
        self.assertIn("후보로 뽑힌 것과 실제 매수 결정은 왜 다른가?", block)

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
