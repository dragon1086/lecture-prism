import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CourseSystemCompletionContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_week3_requires_discord_and_keeps_telegram_optional(self):
        text = self.read("lecture/exercises/part3_실습가이드.md")
        for marker in (
            "Discord", "필수 준비", "웹훅", "DISCORD_WEBHOOK_URL",
            "Telegram", "선택", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "KIS", "모의투자", ".env", ".gitignore",
        ):
            self.assertIn(marker, text, marker)
        self.assertLess(text.index("Discord"), text.index("Telegram"))

    def test_week4_requires_one_strategy_track_then_system_evidence(self):
        text = self.read("lecture/exercises/part4_실습가이드.md")
        for marker in (
            "트랙 A/B/C/D", "System Completion Lane", "data_as_of", "run_id",
            "sequence", "Discord", "Telegram", "accepted", "partial_fill",
            "filled", "blocked", "live_blocked", "대시보드",
        ):
            self.assertIn(marker, text, marker)
        self.assertNotIn("Track E", text)
        self.assertLess(text.index("트랙 A/B/C/D"), text.index("System Completion Lane"))

    def test_curriculum_and_runtime_docs_match_course_outcome(self):
        combined = "\n".join(
            self.read(path)
            for path in (
                "lecture/curriculum.html",
                "docs/api-keys.md",
                "docs/runtime-profiles.md",
                "docs/harness-lite.md",
            )
        )
        for marker in (
            "Discord", "Telegram", "System Completion Lane", "KIS 모의투자",
            "data_as_of", "live_blocked", "알림 실패", "파이프라인은 계속",
        ):
            self.assertIn(marker, combined, marker)

    def test_env_template_exposes_both_channels_and_safe_kis_defaults(self):
        text = self.read(".env.example")
        for marker in (
            "LECTURE_NOTIFY_DISCORD=0", 'DISCORD_WEBHOOK_URL=""',
            "LECTURE_NOTIFY_TELEGRAM=0", 'TELEGRAM_BOT_TOKEN=""',
            'TELEGRAM_CHAT_ID=""', "LECTURE_ENABLE_LIVE_BROKER=0",
            "LECTURE_ALLOW_REAL_BROKER=0",
        ):
            self.assertIn(marker, text, marker)

    def test_student_evidence_never_submits_secrets_or_account_data(self):
        combined = "\n".join(
            self.read(path)
            for path in (
                "lecture/exercises/part3_실습가이드.md",
                "lecture/exercises/part4_실습가이드.md",
                "docs/harness-lite.md",
            )
        )
        for marker in (
            "웹훅 URL을 제출하지", "봇 토큰을 제출하지", "계좌번호를 제출하지",
            ".env를 제출하지", "시크릿 값은 출력하지",
        ):
            self.assertIn(marker, combined, marker)


if __name__ == "__main__":
    unittest.main()
