"""Documentation and service-template contract tests for operations handoff."""

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree


ROOT = Path(__file__).resolve().parents[1]

TEMPLATES = {
    "launchd": ROOT / "deploy" / "launchd" / "com.lecture-prism.operations.plist.example",
    "systemd": ROOT / "deploy" / "systemd" / "lecture-prism.service.example",
    "windows": ROOT / "deploy" / "windows" / "lecture-prism-task.xml.example",
}

DOCS = {
    "runtime": ROOT / "docs" / "runtime-profiles.md",
    "brokers": ROOT / "docs" / "broker-adapters.md",
    "env": ROOT / ".env.example",
}


class OperationsDocumentationContractTest(unittest.TestCase):
    def _read_required(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"missing required artifact: {path}")
        return path.read_text(encoding="utf-8")

    def _templates(self) -> dict[str, str]:
        return {name: self._read_required(path) for name, path in TEMPLATES.items()}

    def _docs(self) -> dict[str, str]:
        return {name: self._read_required(path) for name, path in DOCS.items()}

    def test_service_templates_run_the_project_venv_scheduler_from_project_root(self):
        for name, text in self._templates().items():
            with self.subTest(template=name):
                self.assertIn("operations.py", text)
                self.assertIn("schedule", text)
                self.assertRegex(
                    text,
                    r"\.venv(?:/bin/python|\\Scripts\\python\.exe)",
                )
                self.assertIn("{{PROJECT_DIR}}", text)

    def test_xml_service_templates_parse_from_their_declared_file_bytes(self):
        for name in ("launchd", "windows"):
            with self.subTest(template=name):
                try:
                    ElementTree.fromstring(TEMPLATES[name].read_bytes())
                except ElementTree.ParseError as error:
                    self.fail(f"{name} XML bytes do not match the declared encoding: {error}")

    def test_service_templates_use_os_specific_project_working_directives(self):
        templates = self._templates()
        self.assertRegex(
            templates["launchd"],
            r"<key>WorkingDirectory</key>\s*<string>\{\{PROJECT_DIR\}\}</string>",
        )
        self.assertRegex(
            templates["systemd"],
            r"(?m)^WorkingDirectory=\{\{PROJECT_DIR\}\}$",
        )
        self.assertRegex(
            templates["windows"],
            r"<WorkingDirectory>\{\{PROJECT_DIR\}\}</WorkingDirectory>",
        )

    def test_service_templates_restart_but_do_not_execute_broker_by_default(self):
        restart_contract = {
            "launchd": ("KeepAlive", "RunAtLoad"),
            "systemd": ("Restart=on-failure", "WantedBy=multi-user.target"),
            "windows": ("RestartOnFailure", "BootTrigger"),
        }
        for name, text in self._templates().items():
            with self.subTest(template=name):
                for phrase in restart_contract[name]:
                    self.assertIn(phrase, text)
                self.assertNotIn("--execute-broker", text)

    def test_service_templates_use_placeholders_without_secret_or_personal_paths(self):
        forbidden_patterns = (
            r"/Users/",
            r"/home/[A-Za-z0-9_.-]+/",
            r"[A-Za-z]:\\Users\\",
            r"OPENAI_API_KEY\s*=\s*[^\"\n]+",
            r"KIS_.*SECRET\s*=\s*[^\"\n]+",
            r"DISCORD_WEBHOOK_URL\s*=\s*[^\"\n]+",
        )
        for name, text in self._templates().items():
            with self.subTest(template=name):
                self.assertIn("{{PROJECT_DIR}}", text)
                for pattern in forbidden_patterns:
                    self.assertNotRegex(text, pattern)

    def test_runtime_docs_explain_operations_ladder_and_service_ownership(self):
        runtime = self._docs()["runtime"]
        for phrase in (
            "doctor → simulation → paper → live",
            "operations.py schedule",
            "long-lived service process",
            "service manager",
            "LECTURE_OPERATIONS_RUNTIME_DIR",
            "operations-state.json",
            "logs/operations-YYYY-MM-DD.log",
            "scheduler.lock",
            "status",
        ):
            self.assertIn(phrase, runtime)
        self.assertIn("코딩 에이전트에게 그대로 붙여넣는 프롬프트", runtime)
        self.assertNotIn("```bash", runtime)

    def test_broker_docs_state_readiness_boundaries_for_kis_kiwoom_and_toss(self):
        brokers = self._docs()["brokers"]
        for phrase in (
            "doctor → simulation → paper → live",
            "KIS",
            "키움",
            "Toss",
            "읽기 전용",
            "취소 후 새 주문",
            "UNKNOWN",
            "실제 주문 E2E",
            "READY",
            "CONDITIONAL",
            "BLOCKED",
        ):
            self.assertIn(phrase, brokers)

    def test_env_example_exposes_only_existing_nonsecret_operations_knobs(self):
        env = self._docs()["env"]
        self.assertIn("LECTURE_ENABLE_SCHEDULER=0", env)
        self.assertIn("LECTURE_OPERATIONS_RUNTIME_DIR=", env)
        self.assertIn("LECTURE_UNATTENDED_LIVE_ACK=", env)
        self.assertIn("--monitor-interval-minutes", env)
        self.assertIn("--reconcile-interval-minutes", env)
        self.assertIn("stale_data", env)

        introduced = {
            match.group(1)
            for match in re.finditer(r"^\s*#?\s*(LECTURE_[A-Z0-9_]+)=", env, re.MULTILINE)
        }
        self.assertNotIn("LECTURE_OPERATIONS_MONITOR_INTERVAL_MINUTES", introduced)
        self.assertNotIn("LECTURE_OPERATIONS_RECONCILE_INTERVAL_MINUTES", introduced)
        self.assertNotIn("LECTURE_STALE_QUOTE_SECONDS", introduced)

    def test_beginner_secret_setup_separates_read_only_kis_from_broker_accounts(self):
        docs = self._docs()
        env = docs["env"]
        runtime = docs["runtime"]

        for phrase in (
            "KIS_PAPER_APP_KEY=\"\"",
            "KIS_PAPER_APP_SECRET=\"\"",
            "KIS_REAL_APP_KEY=\"\"",
            "KIS_REAL_APP_SECRET=\"\"",
            "읽기 전용 시장 데이터",
            "계좌번호는 필요하지 않습니다",
        ):
            self.assertIn(phrase, env)

        for phrase in (
            "운영체제의 기본 텍스트 편집기",
            "준비됨 / 비어 있음 / 형식 오류",
            ".gitignore",
            "로컬 파일 읽기까지 막지는",
            "모의·실거래 브로커 심화",
        ):
            self.assertIn(phrase, runtime)

    def test_discord_setup_uses_redacted_default_editor_flow_before_execution(self):
        runtime = self._docs()["runtime"]
        discord_section = runtime.split("## 6. Discord로 AI 판단 받기", 1)[1].split(
            "## 7. 보고서 산출물", 1
        )[0]

        for phrase in (
            ".env.example",
            'DISCORD_WEBHOOK_URL=""',
            "운영체제의 기본 텍스트 편집기",
            "직접 입력",
            "준비됨 / 비어 있음 / 형식 오류",
            "아직 main.py는 실행하지 마",
            "값 자체를 출력하지",
        ):
            self.assertIn(phrase, discord_section)

        self.assertNotIn(
            'DISCORD_WEBHOOK_URL="내 Discord 채널에서 만든 Incoming Webhook URL"',
            discord_section,
        )
        self.assertGreaterEqual(discord_section.count("```text"), 2)


if __name__ == "__main__":
    unittest.main()
