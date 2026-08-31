import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class LocalOutputGuidanceTests(unittest.TestCase):
    def test_both_agent_runtimes_have_the_same_local_skills(self):
        for runtime in (".claude", ".codex"):
            fluent = ROOT / runtime / "skills" / "fluent-korean" / "SKILL.md"
            output = ROOT / runtime / "skills" / "lecture-prism-output" / "SKILL.md"
            self.assertTrue(fluent.exists(), fluent)
            self.assertTrue(output.exists(), output)
            self.assertIn("name: fluent-korean", fluent.read_text(encoding="utf-8"))
            self.assertIn("name: lecture-prism-output", output.read_text(encoding="utf-8"))

    def test_interactive_output_style_has_a_self_contained_template(self):
        style = (ROOT / "docs" / "lecture-prism-output-style.md").read_text(encoding="utf-8")
        template = (ROOT / "docs" / "lecture-prism-output-template.html").read_text(encoding="utf-8")
        for phrase in ("reports/interactive/", "핵심 → 근거 → 다음 행동", "1,500자 안팎", "<details open>", "#73d99a"):
            self.assertIn(phrase, style)
        for phrase in ('lang="ko"', "data-search", "data-toggle", "핵심 1문장", "<details", "--green:#73d99a"):
            self.assertIn(phrase, template)

    def test_course_prompt_documents_share_model_and_output_guidance(self):
        paths = (
            ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md",
            ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트4.md",
            ROOT / "강의자료" / "강사용_실습진행_스크립트.md",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for phrase in (
                "gpt-5.6 luna",
                "extra high",
                "fast",
                "fluent-korean",
                "lecture-prism-output-style.md",
                "reports/interactive/",
            ):
                with self.subTest(path=path.name, phrase=phrase):
                    self.assertIn(phrase, text)

        part3 = paths[0].read_text(encoding="utf-8")
        part4 = paths[1].read_text(encoding="utf-8")
        instructor = paths[2].read_text(encoding="utf-8")
        self.assertIn("결과가 길어지면", part3)
        self.assertIn("결과가 길어지면", part4)
        self.assertIn("오늘 강사가 보여 줄 네 가지 작업의 순서를", instructor)

    def test_each_prompt_starts_with_a_small_context_contract(self):
        part3 = (ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md").read_text(encoding="utf-8")
        part4 = (ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트4.md").read_text(encoding="utf-8")
        instructor = (ROOT / "강의자료" / "강사용_실습진행_스크립트.md").read_text(encoding="utf-8")

        part3_blocks = re.findall(r"```text\n(.*?)\n```", part3, flags=re.DOTALL)
        part4_blocks = re.findall(r"```text\n(.*?)\n```", part4, flags=re.DOTALL)
        instructor_blocks = re.findall(r"```text\n(.*?)\n```", instructor, flags=re.DOTALL)
        self.assertTrue(part3_blocks)
        self.assertTrue(part4_blocks)
        self.assertTrue(instructor_blocks)
        first_nonempty = lambda block: next(line for line in block.splitlines() if line.strip())
        second_nonempty = lambda block: next(
            line for line in block.splitlines()[1:] if line.strip()
        )
        self.assertTrue(all(first_nonempty(block).startswith("컨텍스트:") for block in part3_blocks))
        self.assertTrue(all(second_nonempty(block).startswith("컨텍스트:") for block in part4_blocks))
        self.assertTrue(all(first_nonempty(block).startswith("컨텍스트:") for block in instructor_blocks))

    def test_external_data_prompts_reference_the_runtime_preflight(self):
        paths = (
            ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트3.md",
            ROOT / "lecture" / "exercises" / "수강생_붙여넣기_프롬프트_파트4.md",
            ROOT / "강의자료" / "강사용_실습진행_스크립트.md",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("runtime-execution-preflight.md", text)
        preflight = (ROOT / "docs" / "runtime-execution-preflight.md").read_text(encoding="utf-8")
        for phrase in (".venv", "Python 3.10", "DNS", "승인된 외부 네트워크", "최대 2회", "주문·취소·정정·잔고·계좌"):
            self.assertIn(phrase, preflight)


if __name__ == "__main__":
    unittest.main()
