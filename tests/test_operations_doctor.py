from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from brokers.base import BrokerQuote


class FakeKISDoctorAdapter:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.order_calls: list[str] = []

    def _record(self, name: str):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(
                "failed with app-secret paper-secret account paper-account "
                "https://discord.com/api/webhooks/raw"
            )

    async def check_authentication(self):
        self._record("authentication")
        return {"authenticated": True}

    async def is_market_open(self):
        self._record("market_day")
        return {"business_date": "20260810", "is_open": True}

    async def get_account(self):
        self._record("account_access")
        return {"positions": [{"pdno": "005930", "hldg_qty": "1"}], "summary": []}

    async def get_orderable_quantity(self, ticker, price):
        self._record("orderable_quantity")
        return 3

    async def get_quote(self, ticker):
        self._record("fresh_quote")
        return BrokerQuote(
            ticker=ticker,
            price=70100,
            currency="KRW",
            market="KRX",
            observed_at=datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc),
            source="fake.kis",
        )

    async def get_pending_orders(self, *, business_date=None):
        self._record("pending_order_inquiry")
        return {"rows": [], "summary": []}

    async def place_order(self, order):
        self.order_calls.append("place_order")
        raise AssertionError("doctor must not place orders")

    async def cancel_order(self, order_no, **details):
        self.order_calls.append("cancel_order")
        raise AssertionError("doctor must not cancel orders")


class FakeKiwoomDoctorAdapter:
    def __init__(
        self, *, missing: str | None = None, unavailable: str | None = None
    ) -> None:
        self.missing = missing
        self.unavailable = unavailable
        self.calls: list[str] = []
        self.order_calls: list[str] = []

    def __getattribute__(self, name):
        missing = object.__getattribute__(self, "missing")
        unavailable = object.__getattribute__(self, "unavailable")
        if name == missing:
            raise AttributeError(name)
        if name == unavailable:
            return "not callable"
        return object.__getattribute__(self, name)

    def _record(self, name: str):
        self.calls.append(name)

    async def check_authentication(self):
        self._record("authentication")
        return {"authenticated": True}

    async def get_account(self):
        self._record("account_access")
        return {"positions": [{"pdno": "005930", "hldg_qty": "1"}]}

    async def get_orderable_quantity(self, ticker, price):
        self._record("orderable_quantity")
        return 3

    async def get_sellable_quantity(self, ticker):
        self._record("sellable_quantity")
        return 1

    async def get_quote(self, ticker):
        self._record("fresh_quote")
        return BrokerQuote(
            ticker=ticker,
            price=70100,
            currency="KRW",
            market="KRX",
            observed_at=datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc),
            source="fake.kiwoom",
        )

    async def get_pending_orders(self, *, business_date=None):
        self._record("pending_order_inquiry")
        return {"rows": []}

    async def get_completed_orders(self, *, business_date=None):
        self._record("completed_order_inquiry")
        return {"rows": []}

    async def cancel_order(self, order_no, **details):
        self.order_calls.append("cancel_order")
        raise AssertionError("doctor must not cancel orders")


class FakeTossOfficialDoctorAdapter:
    integration = "official_open_api"

    def __init__(self, *, fail_at: str | None = None, unknown_status: bool = False) -> None:
        self.fail_at = fail_at
        self.unknown_status = unknown_status
        self.calls: list[str] = []
        self.order_calls: list[str] = []

    def _record(self, name: str):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError("official read-only failure raw secret detail")

    async def check_authentication(self):
        self._record("authentication")
        return {"authenticated": True}

    async def get_account(self):
        self._record("account_access")
        return {"accounts_count": 1}

    async def get_sellable_quantity(self, ticker):
        self._record("holdings")
        return 2

    async def get_quote(self, ticker):
        self._record("fresh_quote")
        return object()

    async def get_pending_orders(self):
        self._record("pending_order_inquiry")
        return [{"order_no": "ord-1", "status": "accepted"}]

    async def get_order_status(self, order_no):
        self._record("lifecycle_fixture")
        if self.unknown_status:
            return {"status": "unknown", "terminal": False}
        return {"status": "accepted", "terminal": False}

    async def place_order(self, order):
        self.order_calls.append("place_order")
        raise AssertionError("doctor must not place orders")

    async def cancel_order(self, order_no, **details):
        self.order_calls.append("cancel_order")
        raise AssertionError("doctor must not cancel orders")


class FakeTossWTSDoctorAdapter:
    integration = "wts"

    def __init__(
        self,
        *,
        expired: bool = False,
        malformed_pending: bool = False,
        unknown_status: bool = False,
    ) -> None:
        self.expired = expired
        self.malformed_pending = malformed_pending
        self.unknown_status = unknown_status
        self.calls: list[str] = []
        self.order_calls: list[str] = []

    async def check_auth(self):
        self.calls.append("authentication")
        if self.expired:
            return {"success": False, "status": "blocked", "message": "session expired"}
        return {"success": True, "status": "active"}

    async def get_account(self):
        self.calls.append("account_access")
        return {"orderable_amount_krw": 100000}

    async def get_sellable_quantity(self, ticker):
        self.calls.append("holdings")
        return 2

    async def get_quote(self, ticker):
        self.calls.append("fresh_quote")
        return object()

    async def get_pending_orders(self):
        self.calls.append("pending_order_inquiry")
        if self.malformed_pending:
            return {"orders": []}
        return [{"id": "2026-07-20/10", "status": "accepted"}]

    async def get_order_status(self, order_no):
        self.calls.append("lifecycle_fixture")
        if self.unknown_status:
            return {"status": "unknown", "terminal": False}
        return {"status": "accepted", "terminal": False}

    async def place_order(self, order):
        self.order_calls.append("place_order")
        raise AssertionError("doctor must not place orders")

    async def cancel_order(self, order_no, **details):
        self.order_calls.append("cancel_order")
        raise AssertionError("doctor must not cancel orders")


class OperationsDoctorReportTest(unittest.TestCase):
    def test_report_verdict_uses_highest_severity_check(self):
        from operations_doctor import CheckResult, DoctorReport

        report = DoctorReport.from_checks(
            [
                CheckResult("runtime", "READY", "configured"),
                CheckResult("research", "CONDITIONAL", "missing optional tools"),
                CheckResult("kis", "BLOCKED", "missing credentials"),
            ]
        )

        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual([check.name for check in report.checks], ["kis", "research", "runtime"])

    def test_format_report_redacts_secret_values_and_account_numbers(self):
        from operations_doctor import CheckResult, DoctorReport, format_doctor_report

        report = DoctorReport.from_checks(
            [
                CheckResult(
                    "kis_authentication",
                    "BLOCKED",
                    "failed app-secret paper-secret account paper-account sk-test "
                    "https://discord.com/api/webhooks/raw",
                )
            ]
        )

        rendered = format_doctor_report(
            report,
            secrets=("paper-secret", "paper-account"),
        )

        self.assertIn("verdict: BLOCKED", rendered)
        self.assertIn("<redacted>", rendered)
        self.assertNotIn("app-secret", rendered)
        self.assertNotIn("paper-secret", rendered)
        self.assertNotIn("paper-account", rendered)
        self.assertNotIn("sk-test", rendered)
        self.assertNotIn("discord.com", rendered)


class OperationsDoctorKISReadinessTest(unittest.TestCase):
    def _ready_paper_env(self):
        return {
            "LECTURE_PROFILE": "paper",
            "LECTURE_BROKER": "kis",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "KIS_PAPER_APP_KEY": "paper-key",
            "KIS_PAPER_APP_SECRET": "paper-secret",
            "KIS_PAPER_ACCOUNT_NO": "paper-account",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def test_paper_kis_doctor_blocks_missing_credentials_without_adapter_calls(self):
        from operations_doctor import run_doctor

        class Factory:
            called = False

            def __call__(self):
                self.called = True
                raise AssertionError("adapter must not be built without credentials")

        factory = Factory()
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env={
                    "LECTURE_PROFILE": "paper",
                    "LECTURE_BROKER": "kis",
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                },
                kis_adapter_factory=factory,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kis_credentials"].status, "BLOCKED")
        self.assertFalse(factory.called)

    def test_paper_kis_doctor_runs_only_read_only_capability_checks(self):
        from operations_doctor import run_doctor

        adapter = FakeKISDoctorAdapter()
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
                now=lambda: datetime(2026, 8, 10, 10, 0),
            )
        )

        self.assertEqual(report.verdict, "READY")
        self.assertEqual(
            adapter.calls,
            [
                "authentication",
                "market_day",
                "account_access",
                "orderable_quantity",
                "fresh_quote",
                "pending_order_inquiry",
            ],
        )
        self.assertEqual(adapter.order_calls, [])

    def test_kis_readiness_sanitizes_read_only_failures(self):
        from operations_doctor import format_doctor_report, run_doctor

        adapter = FakeKISDoctorAdapter(fail_at="account_access")
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        rendered = format_doctor_report(
            report,
            secrets=("paper-secret", "paper-account"),
        )

        self.assertEqual(report.verdict, "BLOCKED")
        self.assertIn("kis_account_access", rendered)
        self.assertIn("read-only capability unavailable", rendered)
        self.assertNotIn("failed with", rendered)
        self.assertNotIn("app-secret", rendered)
        self.assertNotIn("paper-secret", rendered)
        self.assertNotIn("paper-account", rendered)
        self.assertNotIn("discord.com", rendered)

    def test_doctor_does_not_create_or_write_runtime_artifacts(self):
        from operations_doctor import run_doctor

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "missing-runtime"
            report = asyncio.run(
                run_doctor(
                    profile="mock",
                    env={"LECTURE_OPERATIONS_RUNTIME_DIR": str(runtime_dir)},
                    unresolved_order_count=lambda: 0,
                    project_root=Path.cwd(),
                )
            )

            self.assertFalse(runtime_dir.exists())

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["local_runtime_dir"].status, "BLOCKED")
        self.assertEqual(checks["local_runtime_dir"].message, "not created")

    def test_doctor_reports_existing_unwritable_runtime_directory_separately(self):
        from operations_doctor import run_doctor

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            runtime_dir.mkdir()
            report = asyncio.run(
                run_doctor(
                    profile="mock",
                    env={"LECTURE_OPERATIONS_RUNTIME_DIR": str(runtime_dir)},
                    unresolved_order_count=lambda: 0,
                    directory_writable=lambda _path: False,
                    project_root=Path.cwd(),
                )
            )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["local_runtime_dir"].status, "BLOCKED")
        self.assertEqual(checks["local_runtime_dir"].message, "not writable")

    def test_missing_pending_order_capability_blocks_kis_readiness(self):
        from operations_doctor import run_doctor

        class NoPendingOrdersAdapter:
            def __init__(self):
                self.get_order_status_calls = 0

            async def check_authentication(self):
                return {"authenticated": True}

            async def is_market_open(self):
                return {"is_open": True}

            async def get_account(self):
                return {"positions": [], "summary": []}

            async def get_orderable_quantity(self, ticker, price):
                return 1

            async def get_quote(self, ticker):
                return BrokerQuote(
                    ticker=ticker,
                    price=70100,
                    currency="KRW",
                    market="KRX",
                    observed_at=datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc),
                    source="fake.kis",
                )

            async def get_order_status(self, order_no, *, business_date=None):
                self.get_order_status_calls += 1
                return {"rows": []}

        adapter = NoPendingOrdersAdapter()
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kis_pending_order_inquiry"].status, "BLOCKED")
        self.assertEqual(adapter.get_order_status_calls, 0)

    def test_provider_exception_contents_never_appear_in_doctor_output(self):
        from operations_doctor import format_doctor_report, run_doctor

        class ProviderFailureAdapter(FakeKISDoctorAdapter):
            async def get_account(self):
                raise RuntimeError(
                    "provider quota exhausted raw stack trace internal detail"
                )

        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=ProviderFailureAdapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )
        rendered = format_doctor_report(report)

        self.assertIn("kis_account_access", rendered)
        self.assertNotIn("provider", rendered)
        self.assertNotIn("quota", rendered)
        self.assertNotIn("raw stack trace", rendered)
        self.assertNotIn("internal detail", rendered)

    def test_adapter_factory_failure_becomes_blocked_without_exception_text(self):
        from operations_doctor import format_doctor_report, run_doctor

        def factory():
            raise RuntimeError("factory provider raw secret detail")

        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=factory,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )
        rendered = format_doctor_report(report)
        checks = {check.name: check for check in report.checks}

        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kis_adapter"].status, "BLOCKED")
        self.assertNotIn("factory provider raw secret detail", rendered)

    def test_print_doctor_writes_sanitized_report(self):
        from operations_doctor import print_doctor

        adapter = FakeKISDoctorAdapter()
        output = StringIO()
        asyncio.run(
            print_doctor(
                output=output,
                profile="paper",
                env=self._ready_paper_env(),
                kis_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        text = output.getvalue()
        self.assertIn("verdict: READY", text)
        self.assertNotIn("paper-secret", text)
        self.assertNotIn("paper-account", text)

    def test_operations_cli_doctor_does_not_load_runtime_context(self):
        import argparse
        import operations

        args = argparse.Namespace(
            command="doctor",
            ticker=None,
            broker=None,
            profile="paper",
            execute_broker=False,
            once=False,
            monitor_interval_minutes=10,
            reconcile_interval_minutes=30,
        )

        with mock.patch(
            "operations._load_runtime_context_without_env_mutation",
            side_effect=AssertionError("doctor must not read dotenv runtime context"),
        ), mock.patch(
            "operations_doctor.print_doctor",
            new=mock.AsyncMock(),
        ) as print_doctor:
            asyncio.run(operations._main(args))

        print_doctor.assert_awaited_once()
        self.assertEqual(print_doctor.await_args.kwargs["profile"], "paper")


class OperationsDoctorKiwoomReadinessTest(unittest.TestCase):
    def _ready_paper_env(self):
        return {
            "LECTURE_PROFILE": "paper",
            "LECTURE_BROKER": "kiwoom",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "KIWOOM_ACCESS_TOKEN": "kw-token",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def test_paper_kiwoom_doctor_runs_read_only_lifecycle_checks_without_mutations(self):
        from operations_doctor import run_doctor

        adapter = FakeKiwoomDoctorAdapter()
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kiwoom_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
                now=lambda: datetime(2026, 8, 10, 10, 0),
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kiwoom_cancel_capability"].status, "BLOCKED")
        self.assertEqual(
            checks["kiwoom_cancel_capability"].message,
            "order-level cancellation E2E approval required; cancel_order not invoked",
        )
        self.assertEqual(
            adapter.calls,
            [
                "authentication",
                "account_access",
                "orderable_quantity",
                "sellable_quantity",
                "fresh_quote",
                "pending_order_inquiry",
                "completed_order_inquiry",
            ],
        )
        self.assertEqual(adapter.order_calls, [])

    def test_missing_kiwoom_lifecycle_capability_blocks_doctor_by_name(self):
        from operations_doctor import run_doctor

        adapter = FakeKiwoomDoctorAdapter(missing="get_pending_orders")
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kiwoom_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kiwoom_pending_order_inquiry"].status, "BLOCKED")
        self.assertEqual(checks["kiwoom_pending_order_inquiry"].message, "missing capability: get_pending_orders")

    def test_missing_kiwoom_completed_order_inquiry_blocks_doctor_by_name(self):
        from operations_doctor import run_doctor

        adapter = FakeKiwoomDoctorAdapter(missing="get_completed_orders")
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kiwoom_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertIn("kiwoom_completed_order_inquiry", checks)
        self.assertEqual(checks["kiwoom_completed_order_inquiry"].status, "BLOCKED")
        self.assertEqual(
            checks["kiwoom_completed_order_inquiry"].message,
            "missing capability: get_completed_orders",
        )

    def test_missing_kiwoom_cancel_capability_blocks_doctor_without_cancel_call(self):
        from operations_doctor import run_doctor

        adapter = FakeKiwoomDoctorAdapter(missing="cancel_order")
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kiwoom_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertIn("kiwoom_cancel_capability", checks)
        self.assertEqual(checks["kiwoom_cancel_capability"].status, "BLOCKED")
        self.assertEqual(
            checks["kiwoom_cancel_capability"].message,
            "missing capability: cancel_order",
        )
        self.assertEqual(adapter.order_calls, [])

    def test_unavailable_kiwoom_cancel_capability_blocks_doctor_without_cancel_call(self):
        from operations_doctor import run_doctor

        adapter = FakeKiwoomDoctorAdapter(unavailable="cancel_order")
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env=self._ready_paper_env(),
                kiwoom_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kiwoom_cancel_capability"].status, "BLOCKED")
        self.assertEqual(
            checks["kiwoom_cancel_capability"].message,
            "unavailable capability: cancel_order",
        )
        self.assertEqual(adapter.order_calls, [])

    def test_paper_kiwoom_doctor_blocks_missing_credentials_without_adapter_calls(self):
        from operations_doctor import run_doctor

        class Factory:
            called = False

            def __call__(self):
                self.called = True
                raise AssertionError("adapter must not be built without credentials")

        factory = Factory()
        report = asyncio.run(
            run_doctor(
                profile="paper",
                env={
                    "LECTURE_PROFILE": "paper",
                    "LECTURE_BROKER": "kiwoom",
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                },
                kiwoom_adapter_factory=factory,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["kiwoom_credentials"].status, "BLOCKED")
        self.assertFalse(factory.called)


class OperationsDoctorTossReadinessTest(unittest.TestCase):
    def _official_live_env(self):
        return {
            "LECTURE_PROFILE": "live",
            "LECTURE_BROKER": "toss",
            "LECTURE_TOSS_INTEGRATION": "official",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "LECTURE_ALLOW_REAL_BROKER": "1",
            "LECTURE_UNATTENDED_LIVE_ACK": "I_ACCEPT_REAL_ORDERS",
            "TOSS_OPENAPI_CLIENT_ID": "client-id",
            "TOSS_OPENAPI_CLIENT_SECRET": "client-secret",
            "TOSS_OPENAPI_ACCOUNT_SEQ": "7",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def _wts_live_env(self):
        return {
            "LECTURE_PROFILE": "live",
            "LECTURE_BROKER": "toss",
            "LECTURE_TOSS_INTEGRATION": "wts",
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "LECTURE_ALLOW_REAL_BROKER": "1",
            "LECTURE_UNATTENDED_LIVE_ACK": "I_ACCEPT_REAL_ORDERS",
            "TOSSCTL_PATH": "/safe/fake/tossctl",
            "OPENAI_API_KEY": "sk-test",
            "PERPLEXITY_API_KEY": "pplx-test",
            "FIRECRAWL_API_KEY": "fc-test",
        }

    def test_toss_paper_is_blocked_without_building_adapter(self):
        from operations_doctor import run_doctor

        class Factory:
            called = False

            def __call__(self):
                self.called = True
                raise AssertionError("Toss paper has no demo adapter")

        official_factory = Factory()
        wts_factory = Factory()

        report = asyncio.run(
            run_doctor(
                profile="paper",
                env={
                    "LECTURE_PROFILE": "paper",
                    "LECTURE_BROKER": "toss",
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                },
                toss_official_adapter_factory=official_factory,
                toss_wts_adapter_factory=wts_factory,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_paper"].status, "BLOCKED")
        self.assertFalse(official_factory.called)
        self.assertFalse(wts_factory.called)

    def test_official_toss_live_runs_read_only_checks_and_remains_conditional(self):
        from operations_doctor import run_doctor

        adapter = FakeTossOfficialDoctorAdapter()
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._official_live_env(),
                toss_official_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "CONDITIONAL")
        self.assertEqual(checks["toss_official_credentials"].status, "READY")
        self.assertEqual(checks["toss_official_order_e2e"].status, "CONDITIONAL")
        self.assertEqual(
            adapter.calls,
            [
                "authentication",
                "account_access",
                "holdings",
                "fresh_quote",
                "pending_order_inquiry",
                "lifecycle_fixture",
            ],
        )
        self.assertEqual(adapter.order_calls, [])

    def test_official_toss_default_factory_blocks_unwired_read_client_without_outputting_credentials(self):
        from operations_doctor import format_doctor_report, run_doctor

        env = self._official_live_env()
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=env,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )
        rendered = format_doctor_report(
            report,
            secrets=(
                env["TOSS_OPENAPI_CLIENT_ID"],
                env["TOSS_OPENAPI_CLIENT_SECRET"],
                env["TOSS_OPENAPI_ACCOUNT_SEQ"],
            ),
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(
            checks["toss_official_read_client_integration"].status,
            "BLOCKED",
        )
        self.assertIn("not wired", checks["toss_official_read_client_integration"].message)
        self.assertNotIn(env["TOSS_OPENAPI_CLIENT_ID"], rendered)
        self.assertNotIn(env["TOSS_OPENAPI_CLIENT_SECRET"], rendered)
        self.assertNotIn(env["TOSS_OPENAPI_ACCOUNT_SEQ"], rendered)

    def test_official_toss_live_blocks_missing_credentials_without_adapter_calls(self):
        from operations_doctor import run_doctor

        class Factory:
            called = False

            def __call__(self):
                self.called = True
                raise AssertionError("adapter must not be built without credentials")

        factory = Factory()
        report = asyncio.run(
            run_doctor(
                profile="live",
                env={
                    "LECTURE_PROFILE": "live",
                    "LECTURE_BROKER": "toss",
                    "LECTURE_TOSS_INTEGRATION": "official",
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                },
                toss_official_adapter_factory=factory,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_official_credentials"].status, "BLOCKED")
        self.assertFalse(factory.called)

    def test_official_toss_rate_limit_blocks_and_sanitizes_failure(self):
        from operations_doctor import format_doctor_report, run_doctor

        adapter = FakeTossOfficialDoctorAdapter(fail_at="account_access")
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._official_live_env(),
                toss_official_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )
        rendered = format_doctor_report(report, secrets=("client-secret",))

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_official_account_access"].status, "BLOCKED")
        self.assertNotIn("raw secret detail", rendered)
        self.assertNotIn("client-secret", rendered)
        self.assertEqual(adapter.order_calls, [])

    def test_official_order_e2e_is_blocked_when_a_read_only_prerequisite_fails(self):
        from operations_doctor import run_doctor

        adapter = FakeTossOfficialDoctorAdapter(fail_at="account_access")
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._official_live_env(),
                toss_official_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(checks["toss_official_account_access"].status, "BLOCKED")
        self.assertEqual(checks["toss_official_order_e2e"].status, "BLOCKED")
        self.assertIn("prerequisite", checks["toss_official_order_e2e"].message)
        self.assertEqual(adapter.order_calls, [])

    def test_official_toss_unknown_lifecycle_blocks_readiness(self):
        from operations_doctor import run_doctor

        adapter = FakeTossOfficialDoctorAdapter(unknown_status=True)
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._official_live_env(),
                toss_official_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_official_lifecycle_fixture"].status, "BLOCKED")
        self.assertEqual(adapter.order_calls, [])

    def test_wts_toss_live_runs_read_only_checks_but_is_never_ready(self):
        from operations_doctor import run_doctor

        adapter = FakeTossWTSDoctorAdapter()
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._wts_live_env(),
                toss_wts_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_wts_live_boundary"].status, "BLOCKED")
        self.assertEqual(
            adapter.calls,
            [
                "authentication",
                "account_access",
                "holdings",
                "fresh_quote",
                "pending_order_inquiry",
                "lifecycle_fixture",
            ],
        )
        self.assertEqual(adapter.order_calls, [])

    def test_wts_toss_expired_session_blocks_before_read_checks(self):
        from operations_doctor import run_doctor

        adapter = FakeTossWTSDoctorAdapter(expired=True)
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._wts_live_env(),
                toss_wts_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_wts_authentication"].status, "BLOCKED")
        self.assertEqual(adapter.calls, ["authentication"])
        self.assertEqual(adapter.order_calls, [])

    def test_wts_toss_malformed_pending_payload_blocks_readiness(self):
        from operations_doctor import run_doctor

        adapter = FakeTossWTSDoctorAdapter(malformed_pending=True)
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._wts_live_env(),
                toss_wts_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_wts_pending_order_inquiry"].status, "BLOCKED")
        self.assertEqual(adapter.order_calls, [])

    def test_wts_toss_unknown_lifecycle_blocks_readiness(self):
        from operations_doctor import run_doctor

        adapter = FakeTossWTSDoctorAdapter(unknown_status=True)
        report = asyncio.run(
            run_doctor(
                profile="live",
                env=self._wts_live_env(),
                toss_wts_adapter_factory=lambda: adapter,
                unresolved_order_count=lambda: 0,
                directory_writable=lambda _path: True,
            )
        )

        checks = {check.name: check for check in report.checks}
        self.assertEqual(report.verdict, "BLOCKED")
        self.assertEqual(checks["toss_wts_lifecycle_fixture"].status, "BLOCKED")
        self.assertEqual(adapter.order_calls, [])


if __name__ == "__main__":
    unittest.main()
