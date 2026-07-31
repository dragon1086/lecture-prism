import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SLIDE = ROOT / "lecture" / "slides" / "사전오픈_세미나_슬라이드.html"
REQUIREMENTS = ROOT / "requirements.txt"
RUNTIME_PROFILES = ROOT / "docs" / "runtime-profiles.md"


class ReadmeOutcomeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")
        cls.slide = SLIDE.read_text(encoding="utf-8")
        cls.requirements = REQUIREMENTS.read_text(encoding="utf-8").lower()
        cls.runtime_profiles = RUNTIME_PROFILES.read_text(encoding="utf-8")

    def test_readme_is_a_short_four_image_course_preview(self):
        self.assertLessEqual(len(self.readme.splitlines()), 150)
        self.assertEqual(self.readme.count("!["), 4)
        self.assertIn("docs/assets/readme/strategy-to-kis.png", self.readme)
        self.assertIn("docs/assets/readme/system-result.png", self.readme)
        self.assertIn("docs/assets/readme/strategy-tracks.png", self.readme)
        self.assertIn("docs/assets/readme/system-sapling.png", self.readme)

    def test_readme_promises_keyless_start_and_kis_modes_in_one_project(self):
        self.assertIn("API 키 없이", self.readme)
        self.assertIn(".env", self.readme)
        self.assertIn("kis_devlp.yaml", self.readme)
        self.assertIn("KIS 모의투자", self.readme)
        self.assertIn("KIS 실전투자", self.readme)
        self.assertNotIn("LECTURE_ALLOW_REAL_BROKER", self.readme)

    def test_readme_keeps_the_first_run_simple_but_names_current_broker_scope(self):
        for phrase in (
            "기본 학습 경로",
            "상태 기반 고급 경로",
            "매수·매도·조회·취소·재시작 reconcile",
        ):
            self.assertIn(phrase, self.readme)
        self.assertNotIn("KIS 실전투자 매수 주문 경로", self.readme)

    def test_kis_bridge_optional_dependencies_and_beginner_setup_are_documented(self):
        for package in (
            "pandas",
            "tenacity",
            "requests",
            "websockets",
            "pyyaml",
            "pycryptodome",
            "cryptography",
        ):
            self.assertIn(package, self.requirements)
        self.assertIn("KIS 연결에 필요한 선택 패키지", self.runtime_profiles)
        self.assertIn("코딩 에이전트", self.runtime_profiles)

    def test_readme_keeps_the_four_strategy_tracks_as_the_student_action(self):
        self.assertIn("내 전략을 넣는 네 가지 트랙", self.readme)
        for label in ("A · 진입", "B · 분석", "C · 청산", "D · 리스크"):
            self.assertIn(label, self.readme)

    def test_harness_applies_the_whole_strategy_one_track_at_a_time(self):
        self.assertIn("전체 전략을 네 영역으로", self.readme)
        self.assertIn("한 영역씩", self.readme)
        self.assertIn("수정 → 검증 → 전후 비교", self.readme)
        self.assertIn("다음 영역", self.readme)
        self.assertIn("A·C·D", self.readme)
        self.assertIn("B 트랙", self.readme)
        self.assertIn("실제 문장 변화", self.readme)

    def test_readme_frames_the_project_as_a_system_to_keep_growing(self):
        for phrase in (
            "나무 모종",
            "매매 로직",
            "모니터링",
            "대시보드",
            "Discord 판단 알림",
        ):
            self.assertIn(phrase, self.readme)

    def test_seminar_slide_matches_the_readme_payoff(self):
        for phrase in (
            "API 키 없이",
            "실데이터",
            "실제 AI",
            "KIS",
            "내 전략을 넣는 네 가지 트랙",
            "모의·실전",
            "매수 주문 경로",
            "한 영역씩",
            "나무 모종",
        ):
            self.assertIn(phrase, self.slide)


if __name__ == "__main__":
    unittest.main()
