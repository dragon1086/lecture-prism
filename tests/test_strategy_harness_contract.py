import ast
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StrategyHarnessContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_skill_copies_share_required_contract(self):
        paths = [
            ".codex/skills/lecture-prism-strategy-harness/SKILL.md",
            ".claude/skills/lecture-prism-strategy-harness/SKILL.md",
            ".agents/skills/lecture-prism-strategy-harness/SKILL.md",
        ]
        required = [
            "수업 빠른 모드",
            "지금 사용 가능",
            "무료 연결 가능",
            "키 또는 계정 필요",
            "사람이 넣어야 함",
            "이번 범위 밖",
            "System Completion Lane",
            "Discord",
            "Telegram",
            "data_as_of",
            "run_id",
            "sequence",
            "live_blocked",
        ]
        contents = [self.read(path) for path in paths]
        self.assertEqual(contents[0], contents[1])
        self.assertEqual(contents[0], contents[2])
        for path, text in zip(paths, contents):
            for marker in required:
                self.assertIn(marker, text, f"{path}: {marker}")
            self.assertNotIn("Track E", text, path)

    def test_harness_reference_copies_are_identical(self):
        for filename in ("track-map.md", "system-completion.md"):
            paths = [
                f".codex/skills/lecture-prism-strategy-harness/references/{filename}",
                f".claude/skills/lecture-prism-strategy-harness/references/{filename}",
                f".agents/skills/lecture-prism-strategy-harness/references/{filename}",
            ]
            contents = [self.read(path) for path in paths]
            self.assertEqual(contents[0], contents[1], filename)
            self.assertEqual(contents[0], contents[2], filename)

    def test_student_template_captures_extended_strategy(self):
        text = self.read("MY_STRATEGY.md")
        for marker in ["시장 흐름", "필요한 자료", "직접 넣을 자료", "기억", "서로 충돌"]:
            self.assertIn(marker, text)

    def test_docs_keep_one_track_classroom_flow(self):
        text = self.read("docs/harness-lite.md")
        for marker in ["35분", "한 트랙", "API 키 없이", "Windows", "Python 3.10"]:
            self.assertIn(marker, text)

    def test_agent_roles_use_beginner_friendly_extended_contract(self):
        paths = [
            ".codex/agents/lecture-strategy-interviewer.toml",
            ".codex/agents/lecture-strategy-implementer.toml",
            ".codex/agents/lecture-strategy-verifier.toml",
            ".claude/agents/lecture-strategy-interviewer.md",
            ".claude/agents/lecture-strategy-implementer.md",
            ".claude/agents/lecture-strategy-verifier.md",
        ]
        required = [
            "수업 빠른 모드",
            "쉬운 말",
            "자료 준비 상태",
            "System Completion Lane",
        ]
        for path in paths:
            text = self.read(path)
            for marker in required:
                self.assertIn(marker, text, f"{path}: {marker}")

    def test_local_sensitive_inputs_are_ignored(self):
        ignore_text = self.read(".gitignore")
        samples = [
            ("student_inputs/", "student_inputs/paid-report.md"),
            ("lecture/slides/assets/", "lecture/slides/assets/kis-account-example.jpeg"),
        ]
        for marker, sample in samples:
            self.assertIn(marker, ignore_text)
            result = subprocess.run(
                ["git", "check-ignore", "-q", sample],
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(result.returncode, 0, sample)

    def test_demo_python_is_valid_python_310_without_local_absolute_paths(self):
        files = [
            ROOT / name
            for name in [
                "main.py",
                "analysis.py",
                "screening.py",
                "trading.py",
                "feedback.py",
                "db.py",
                "dashboard.py",
                "runtime_config.py",
            ]
        ]
        files.extend(sorted((ROOT / "brokers").glob("*.py")))
        local_path = re.compile(r"/Users/|[A-Za-z]:\\\\Users\\\\")
        for path in files:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 10))
            self.assertIsNone(local_path.search(source), str(path))


if __name__ == "__main__":
    unittest.main()
