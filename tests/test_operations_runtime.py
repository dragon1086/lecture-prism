import unittest

import operations_runtime
import runtime_config


class ExecutionPolicyTest(unittest.TestCase):
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

    def test_policy_is_immutable_and_redacts_environment_values(self):
        policy = operations_runtime.resolve_execution_policy(
            "live",
            execute_broker=True,
            env={
                "LECTURE_ENABLE_LIVE_BROKER": "secret-enable",
                "LECTURE_ALLOW_REAL_BROKER": "secret-allow",
                "LECTURE_UNATTENDED_LIVE_ACK": "secret-ack",
            },
        )

        with self.assertRaises(Exception):
            policy.dry_run = False
        self.assertNotIn("secret", repr(policy))


if __name__ == "__main__":
    unittest.main()
