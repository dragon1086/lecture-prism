# Selectable Report Channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let students select Discord, Telegram, both, or no external reporting in `.env` while preserving the keyless mock path and existing Discord installations.

**Architecture:** Keep all decision-message formatters in `notifications.py`, share the stage-level notifier interface across Discord and Telegram transports, and let `build_notifier()` compose the valid providers selected by `LECTURE_REPORT_CHANNEL`. Update course-facing materials from a Discord-only path to a selected-report-channel path, then rebuild the generated Part 3 HTML from its source module.

**Tech Stack:** Python 3 standard library (`asyncio`, `html`, `json`, `re`, `urllib`), `unittest`, static HTML, Node.js deck assembler

**Spec:** `docs/superpowers/specs/2026-09-03-selectable-report-channels-design.md`

## Global Constraints

- `python3 main.py` must complete without API keys, report credentials, or new packages.
- `LECTURE_REPORT_CHANNEL` accepts only `discord`, `telegram`, `both`, and `off`; the documented default selection is `discord`.
- Existing `LECTURE_NOTIFY_DISCORD` is a compatibility input only when the new setting is absent.
- Notification failures never change screening, analysis, trading, feedback, DB, or broker outcomes.
- Bot tokens, webhook URLs, Telegram channel IDs, account identifiers, and balances never enter logs or messages.
- Live-order gates and function signatures remain unchanged.
- Production behavior follows a witnessed RED → GREEN test cycle.
- The generated Part 3 HTML is rebuilt from `강의자료/deck-src/part3/00-opening.html`; generated HTML is not edited directly.

---

### Task 1: Telegram transport and reusable stage notifier

**Files:**
- Modify: `tests/test_notifications.py`
- Modify: `notifications.py`
- Modify: `operations_runtime.py`

**Interfaces:**
- Produces: `is_valid_telegram_bot_token(value: str) -> bool`
- Produces: `is_valid_telegram_channel_id(value: str) -> bool`
- Produces: `TelegramNotifier(bot_token, channel_id, *, opener=urlopen, sleep=time.sleep, timeout_seconds=5.0)`
- Preserves: async `screening`, `analysis`, `trading`, `summary`, `feedback`, and `operational` notifier methods.

- [x] **Step 1: Write failing Telegram validation and payload tests**

```python
VALID_TELEGRAM_TOKEN = "123456789:" + ("A" * 35)
VALID_TELEGRAM_CHANNEL = "-1001234567890"

def test_telegram_payload_uses_fixed_api_host_safe_html_and_no_preview(self):
    opener = FakeOpener(FakeResponse(b'{"ok":true,"result":{"message_id":1}}'))
    notifier = notifications.TelegramNotifier(
        VALID_TELEGRAM_TOKEN,
        VALID_TELEGRAM_CHANNEL,
        opener=opener,
    )
    sent = asyncio.run(notifier.send("**판단** <보류>"))
    request, timeout = opener.requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    self.assertTrue(sent)
    self.assertEqual(request.full_url, f"https://api.telegram.org/bot{VALID_TELEGRAM_TOKEN}/sendMessage")
    self.assertEqual(payload["chat_id"], VALID_TELEGRAM_CHANNEL)
    self.assertEqual(payload["text"], "<b>판단</b> &lt;보류&gt;")
    self.assertEqual(payload["parse_mode"], "HTML")
    self.assertTrue(payload["disable_web_page_preview"])
```

Add independent tests for rejected URL/whitespace credentials, `ok=false`, a bounded 429 retry, and token/channel omission from warning logs.

- [x] **Step 2: Run RED**

Run: `python3 -m unittest tests.test_notifications.TelegramTransportTest -v`

Expected: ERROR or FAIL because `TelegramNotifier` and validators do not exist.

- [x] **Step 3: Implement the minimal reusable notifier boundary**

Extract the existing stage methods from `DiscordNotifier` into a small shared mixin. Implement fixed-host Telegram JSON POST, safe HTML conversion, response validation, one bounded 429 retry, and redacted warnings. Add `channel_id` to operational sensitive-field matching.

- [x] **Step 4: Run GREEN**

Run: `python3 -m unittest tests.test_notifications.TelegramTransportTest tests.test_notifications.DiscordTransportTest tests.test_notifications.DiscordMessageFormatTest -v`

Expected: PASS.

### Task 2: Environment selection, legacy compatibility, and partial success

**Files:**
- Modify: `tests/test_notifications.py`
- Modify: `tests/test_main_runtime_options.py`
- Modify: `notifications.py`
- Modify: `main.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `build_notifier() -> NullNotifier | DiscordNotifier | TelegramNotifier | CompositeNotifier`
- Produces: `CompositeNotifier(notifiers)` whose `send(content)` returns `True` when at least one provider succeeds.
- Consumes: `LECTURE_REPORT_CHANNEL`, `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, and legacy `LECTURE_NOTIFY_DISCORD`.

- [x] **Step 1: Write failing selector and composite tests**

```python
def test_both_builds_two_independent_providers(self):
    with mock.patch.object(notifications, "load_dotenv_once"), mock.patch.dict(
        os.environ,
        {
            "LECTURE_REPORT_CHANNEL": "both",
            "DISCORD_WEBHOOK_URL": VALID_WEBHOOK,
            "TELEGRAM_BOT_TOKEN": VALID_TELEGRAM_TOKEN,
            "TELEGRAM_CHANNEL_ID": VALID_TELEGRAM_CHANNEL,
        },
        clear=False,
    ):
        notifier = notifications.build_notifier()
    self.assertIsInstance(notifier, notifications.CompositeNotifier)
    self.assertEqual(
        [type(item) for item in notifier.notifiers],
        [notifications.DiscordNotifier, notifications.TelegramNotifier],
    )

def test_composite_succeeds_when_one_provider_fails(self):
    notifier = notifications.CompositeNotifier([ResultNotifier(False), ResultNotifier(True)])
    self.assertTrue(asyncio.run(notifier.send("판단")))
```

Add cases for `discord`, `telegram`, `off`, invalid selection, one valid provider under `both`, default Discord without credentials, and legacy `LECTURE_NOTIFY_DISCORD=1/0` when the new key is absent.

- [x] **Step 2: Run RED**

Run: `python3 -m unittest tests.test_notifications.NotificationConfigurationTest tests.test_notifications.CompositeNotifierTest -v`

Expected: FAIL because new selection and composition behavior do not exist.

- [x] **Step 3: Implement the selector and provider composition**

Normalize the new enum, use legacy selection only when the new key is missing, construct only valid requested providers, and return a single provider directly or `CompositeNotifier` for two providers. Change `main._notify()` warning copy from Discord-specific text to `보고 채널`.

Update `.env.example` to contain:

```dotenv
LECTURE_REPORT_CHANNEL=discord
DISCORD_WEBHOOK_URL=""
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHANNEL_ID=""
```

- [x] **Step 4: Run GREEN**

Run: `python3 -m unittest tests.test_notifications tests.test_main_notifications tests.test_main_runtime_options -v`

Expected: PASS for the changed notification and main contracts.

### Task 3: Instructor and student course path

**Files:**
- Modify: `강의자료/강사용_실습진행_스크립트.md`
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md`
- Modify: `강의자료/수업_시작_전_안내.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `docs/runtime-execution-preflight.md`
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `tests/test_notifications.py`
- Modify: `tests/test_part3_student_learning_contract.py`
- Modify: `tests/test_readme_outcome_contract.py`
- Modify: `tests/test_main_runtime_options.py`

**Interfaces:**
- Documents one setting contract: `discord | telegram | both | off`.
- Documents channel-specific credentials without real values.
- Preserves course prompts as copy-and-paste requests rather than terminal instructions.

- [x] **Step 1: Change focused course-contract expectations before prose**

Update the existing notification documentation contract to require all four selection values and both Telegram keys. Update the Part 3 first-run contract to require `선택한 보고 채널`, Discord and Telegram credential names, channel-specific success evidence, and `LECTURE_REPORT_CHANNEL=off` fallback.

- [x] **Step 2: Run the focused contract tests and confirm RED**

Run the affected individual tests from `tests.test_notifications.DiscordDocumentationContractTest`, `tests.test_part3_student_learning_contract.Part3StudentLearningContractTest`, and `tests.test_readme_outcome_contract.ReadmeOutcomeContractTest`.

Expected: FAIL because the course materials are still Discord-only.

- [x] **Step 3: Rewrite the course path consistently**

Use `선택한 보고 채널` for shared behavior. Keep separate Discord and Telegram setup instructions where credentials differ. In every mock fallback or external-connection prohibition, use `LECTURE_REPORT_CHANNEL=off` and name both services. Require reports to distinguish configured channel, actual success per channel, failure reason, and skipped state. Never ask students to paste secrets into chat.

- [x] **Step 4: Run GREEN and scan for stale Discord-only assumptions**

Run the same focused tests. Then run:

`rg -n -i 'Discord를 쓸|Discord 없이|LECTURE_NOTIFY_DISCORD|실데이터·Discord' README.md docs lecture 강의자료 .env.example AGENTS.md tests`

Expected: no maintained course instruction assumes Discord is the only selectable report channel. Legacy variable mentions remain only in compatibility tests or a migration note.

### Task 4: Part 3 slide 5 and generated deck

**Files:**
- Modify: `강의자료/deck-src/part3/00-opening.html`
- Regenerate: `강의자료/파트3_슬라이드.html`
- Verify: `tests/test_part3_deck_contract.py`

**Interfaces:**
- Slide `P3-S05` tells prepared learners to choose Discord or Telegram in `.env` and keep credentials out of chat.
- `강의자료/deck-src/build-decks.mjs` remains the only generator for the final HTML.

- [x] **Step 1: Add the failing slide contract**

```python
def test_slide_five_allows_discord_or_telegram_report_setup(self):
    slide = self._slide("P3-S05")
    self.assertIn("Discord 또는 Telegram", slide)
    self.assertIn("보고 채널", slide)
    self.assertIn(".env", slide)
    self.assertIn("채팅에 붙여넣지", slide)
```

- [x] **Step 2: Run RED**

Run: `python3 -m unittest tests.test_part3_deck_contract.Part3DeckContractTests.test_slide_five_allows_discord_or_telegram_report_setup -v`

Expected: FAIL because slide 5 names Discord only.

- [x] **Step 3: Edit source copy and regenerate both deck outputs**

Shorten the existing two affected sentences so the layout density does not increase. Run `node 강의자료/deck-src/build-decks.mjs` and preserve all slide IDs and module counts.

- [x] **Step 4: Run GREEN and inspect the generated slide**

Run the slide contract and `python3 -m unittest tests.test_part3_deck_contract -v`. Extract generated `P3-S05` and confirm the title remains one claim, the new body does not add a list item, and the report-channel copy appears in the generated HTML.

### Task 5: Verification and delivery readiness

**Files:**
- Review every changed file.
- Update: this plan's checkboxes as work completes.

**Interfaces:**
- Proves keyless demo completion, transport boundaries, course consistency, slide regeneration, and secret hygiene.

- [x] **Step 1: Run focused regression**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-notify-pycache python3 -m unittest tests.test_notifications tests.test_main_notifications tests.test_main_runtime_options tests.test_operations_runtime tests.test_part3_deck_contract -v`

Expected: PASS.

- [x] **Step 2: Run the keyless demo and live-gate proof**

Run: `LECTURE_REPORT_CHANNEL=off PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-demo-pycache python3 main.py`

Run: `LECTURE_REPORT_CHANNEL=off PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-live-pycache python3 trading.py --live`

Expected: the demo completes through feedback and DB storage; live mode returns `live_blocked` without broker calls.

- [x] **Step 3: Compile and inspect generated artifacts**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-compile-pycache python3 -m compileall main.py notifications.py operations_runtime.py`

Run: `git diff --check`

Expected: exit 0.

- [x] **Step 4: Run full regression and compare with the baseline**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-full-pycache python3 -m unittest discover -s tests -v`

Expected: no new failures beyond the 36 pre-existing course-contract failures recorded before implementation. Any changed related test must pass; unrelated baseline failures are reported honestly.

- [x] **Step 5: Audit tracked changes for secrets and scope**

Run: `git status --short`

Run: `git diff --cached --name-only`

Run a tracked-diff pattern scan for non-placeholder bot tokens, webhook values, account identifiers, `.env`, databases, reports, logs, and local absolute paths. Review `git diff` for live-gate changes and unintended generated-file edits.

Expected: only intended source, tests, docs, plan/spec, and generated Part 3 HTML are present; no actual secret or local output is staged.
