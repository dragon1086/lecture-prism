from pathlib import Path
import unittest

import operations_runtime
import runtime_config


class ExecutionPolicyTest(unittest.TestCase):
    def test_unattended_ack_constant_is_controller_approved_literal(self):
        self.assertEqual(
            operations_runtime.LIVE_BROKER_UNATTENDED_ACK,
            "I_ACCEPT_REAL_ORDERS",
        )
        self.assertEqual(
            runtime_config.LIVE_BROKER_UNATTENDED_ACK,
            "I_ACCEPT_REAL_ORDERS",
        )

    def test_non_operating_profiles_always_resolve_to_simulation(self):
        for profile in ("mock", "classroom", "real_data", "research", "backtest"):
            for execute_broker in (False, True):
                with self.subTest(profile=profile, execute_broker=execute_broker):
                    policy = operations_runtime.resolve_execution_policy(
                        profile,
                        execute_broker=execute_broker,
                        env={
                            "LECTURE_ENABLE_LIVE_BROKER": "1",
                            "LECTURE_ALLOW_REAL_BROKER": "1",
                            "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
                        },
                    )

                    self.assertEqual(policy.profile, profile)
                    self.assertEqual(policy.account_mode, "simulation")
                    self.assertFalse(policy.broker_execution_allowed)
                    self.assertTrue(policy.dry_run)
                    self.assertIn("profile_forces_simulation", policy.blocked_reasons)

    def test_paper_and_live_without_execute_broker_resolve_to_simulation(self):
        for profile in ("paper", "live"):
            with self.subTest(profile=profile):
                policy = operations_runtime.resolve_execution_policy(
                    profile,
                    execute_broker=False,
                    env={
                        "LECTURE_ENABLE_LIVE_BROKER": "1",
                        "LECTURE_ALLOW_REAL_BROKER": "1",
                        "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
                    },
                )

                self.assertEqual(policy.account_mode, "simulation")
                self.assertFalse(policy.requested_broker_execution)
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertIn("broker_execution_not_requested", policy.blocked_reasons)

    def test_paper_execution_requires_live_broker_enable_gate(self):
        blocked = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={},
        )
        allowed = operations_runtime.resolve_execution_policy(
            "paper",
            execute_broker=True,
            env={"LECTURE_ENABLE_LIVE_BROKER": "1"},
        )

        self.assertEqual(blocked.account_mode, "demo")
        self.assertTrue(blocked.requested_broker_execution)
        self.assertFalse(blocked.broker_execution_allowed)
        self.assertTrue(blocked.dry_run)
        self.assertEqual(blocked.blocked_reasons, ("live_broker_not_enabled",))

        self.assertEqual(allowed.account_mode, "demo")
        self.assertTrue(allowed.requested_broker_execution)
        self.assertTrue(allowed.broker_execution_allowed)
        self.assertFalse(allowed.dry_run)
        self.assertEqual(allowed.blocked_reasons, ())

    def test_live_execution_requires_enable_allow_and_exact_unattended_ack(self):
        old_ack = (
            "I UNDERSTAND THIS LECTURE-PRISM RUN MAY SEND UNATTENDED REAL BROKER ORDERS"
        )
        cases = [
            ({}, "live_broker_not_enabled"),
            ({"LECTURE_ENABLE_LIVE_BROKER": "1"}, "real_broker_not_allowed"),
            (
                {
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": "yes",
                },
                "unattended_live_ack_missing",
            ),
            (
                {
                    "LECTURE_ENABLE_LIVE_BROKER": "1",
                    "LECTURE_ALLOW_REAL_BROKER": "1",
                    "LECTURE_UNATTENDED_LIVE_ACK": old_ack,
                },
                "unattended_live_ack_missing",
            ),
        ]
        for env, reason in cases:
            with self.subTest(reason=reason):
                policy = operations_runtime.resolve_execution_policy(
                    "live",
                    execute_broker=True,
                    env=env,
                )

                self.assertEqual(policy.account_mode, "real")
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertIn(reason, policy.blocked_reasons)

        allowed = operations_runtime.resolve_execution_policy(
            "live",
            execute_broker=True,
            env={
                "LECTURE_ENABLE_LIVE_BROKER": "1",
                "LECTURE_ALLOW_REAL_BROKER": "1",
                "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
            },
        )

        self.assertEqual(allowed.account_mode, "real")
        self.assertTrue(allowed.broker_execution_allowed)
        self.assertFalse(allowed.dry_run)
        self.assertEqual(allowed.blocked_reasons, ())

    def test_dangerous_aliases_and_unknown_profiles_fail_closed(self):
        env = {
            "LECTURE_ENABLE_LIVE_BROKER": "1",
            "LECTURE_ALLOW_REAL_BROKER": "1",
            "LECTURE_UNATTENDED_LIVE_ACK": runtime_config.LIVE_BROKER_UNATTENDED_ACK,
        }

        for profile in ("real", "prod", "broker-demo", "livve"):
            with self.subTest(profile=profile):
                policy = operations_runtime.resolve_execution_policy(
                    profile,
                    execute_broker=True,
                    env=env,
                )

                self.assertEqual(policy.profile, profile)
                self.assertEqual(policy.account_mode, "simulation")
                self.assertFalse(policy.broker_execution_allowed)
                self.assertTrue(policy.dry_run)
                self.assertEqual(policy.blocked_reasons, ("unknown_profile",))

    def test_policy_is_immutable_and_redacts_environment_values(self):
        raw_values = (
            "enable-7ab42d07e2",
            "allow-bc932df31d",
            runtime_config.LIVE_BROKER_UNATTENDED_ACK,
        )
        policy = operations_runtime.resolve_execution_policy(
            "live",
            execute_broker=True,
            env={
                "LECTURE_ENABLE_LIVE_BROKER": raw_values[0],
                "LECTURE_ALLOW_REAL_BROKER": raw_values[1],
                "LECTURE_UNATTENDED_LIVE_ACK": raw_values[2],
            },
        )

        with self.assertRaises(Exception):
            policy.dry_run = False

        policy_strings = (
            repr(policy),
            policy.profile,
            policy.account_mode,
            *policy.blocked_reasons,
        )
        for raw_value in raw_values:
            with self.subTest(raw_value=raw_value):
                for text in policy_strings:
                    self.assertNotIn(raw_value, text)

    def test_env_example_exposes_blank_unattended_ack_key(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("LECTURE_UNATTENDED_LIVE_ACK=", env_example)
        self.assertIn(
            f"# 정확히 이 값으로 바꿔야 실전 무인 주문이 허용됩니다: "
            f"{runtime_config.LIVE_BROKER_UNATTENDED_ACK}",
            env_example,
        )


if __name__ == "__main__":
    unittest.main()
