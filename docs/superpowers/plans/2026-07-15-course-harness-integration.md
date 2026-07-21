# Course and Harness Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Week 3 preparation and Week 4 completion honestly match the observable paper-trading system and teach students to verify it through coding-agent prompts.

**Architecture:** Documentation defines Discord as required preparation and Telegram as optional. Strategy Harness retains A/B/C/D strategy edits and adds a separate System Completion Lane that verifies notifications, latest data date, KIS paper behavior, dashboard evidence, and secret hygiene.

**Tech Stack:** Markdown, HTML curriculum, TOML/Markdown agent prompts, contract tests, Python demo

## Global Constraints

- Student documents contain coding-agent prompts, not direct terminal walkthroughs.
- `.env`, account numbers, webhook URLs, tokens, DBs, logs, and screenshots with secrets are never submitted.
- Three harness skill copies remain byte-identical.
- A/B/C/D remain the only strategy tracks.
- Discord is required as a course artifact but optional at runtime; Telegram is optional in both.

---

### Task 1: Contract tests for course outcomes

**Files:**
- Modify: `tests/test_strategy_harness_contract.py`
- Create: `tests/test_course_system_completion_contract.py`

**Interfaces:**
- Produces: enforced wording and file parity for all later documentation changes

- [ ] **Step 1: Write failing assertions**

```python
self.assertIn("System Completion Lane", skill_text)
self.assertIn("Discord", part3_text)
self.assertIn("Telegram", part3_text)
self.assertIn("data_as_of", verifier_text)
self.assertNotIn("Track E", skill_text)
```

Also require Discord mandatory/Telegram optional, webhook/token secret rules, KIS paper-only smoke checks, dashboard evidence, run ID/sequence, notification fail-open, and live fail-closed.

- [ ] **Step 2: Run and confirm contract failures**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_strategy_harness_contract tests.test_course_system_completion_contract -v`

- [ ] **Step 3: Commit only failing contract tests with a Lore message**

### Task 2: Week 3 and Week 4 student guides

**Files:**
- Modify: `lecture/exercises/part3_실습가이드.md`
- Modify: `lecture/exercises/part4_실습가이드.md`
- Modify: `lecture/curriculum.html`
- Modify: `.env.example`
- Modify: `docs/api-keys.md`
- Modify: `docs/runtime-profiles.md`

**Interfaces:**
- Consumes: runtime variables and status vocabulary from implemented code
- Produces: agent-driven setup and verification prompts

- [ ] **Step 1: Add Week 3 required Discord and KIS paper preparation**

The prompt asks the coding agent to create/check a local `.env`, guide webhook creation, send a harmless test, prepare paper credentials, redact output, and confirm ignored files. It explicitly leaves real-account enable flags off.

- [ ] **Step 2: Add optional Telegram preparation**

The prompt guides BotFather creation, first conversation, chat ID discovery, test message, redaction, and fallback if Telegram is skipped.

- [ ] **Step 3: Add Week 4 completion evidence**

Require one A/B/C/D strategy change, a complete run with latest data date, Discord sequence, optional Telegram parity, dashboard run match, order state truth, and secret-free evidence.

- [ ] **Step 4: Run course contract tests**

Expected: PASS and no direct terminal blocks added to student-facing sections.

- [ ] **Step 5: Commit guides with a Lore message**

### Task 3: Strategy Harness System Completion Lane

**Files:**
- Modify: `.codex/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: `.claude/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: `.agents/skills/lecture-prism-strategy-harness/SKILL.md`
- Modify: matching `references/` files in all copies
- Modify: `.codex/agents/lecture-strategy-interviewer.toml`
- Modify: `.codex/agents/lecture-strategy-implementer.toml`
- Modify: `.codex/agents/lecture-strategy-verifier.toml`
- Modify: `.claude/agents/lecture-strategy-interviewer.md`
- Modify: `.claude/agents/lecture-strategy-implementer.md`
- Modify: `.claude/agents/lecture-strategy-verifier.md`
- Modify: `docs/harness-lite.md`

**Interfaces:**
- Produces: identical harness contract and role-specific verification behavior

- [ ] **Step 1: Preserve Strategy Lane selection and append System Completion Lane**

The lane runs only after the one-track demo passes. It checks notifications, data provenance, market/order safety, dashboard evidence, and secret hygiene; it does not turn integration into Track E.

- [ ] **Step 2: Add official-reference routing**

When KIS work is requested, the harness checks a local official checkout or clones to an ignored `.references/open-trading-api`, records the inspected commit, references official contracts, and avoids copying unlicensed files wholesale.

- [ ] **Step 3: Update interviewer/implementer/verifier responsibilities**

Interviewer infers configured channels without printing values. Implementer edits focused system files only after strategy verification. Verifier runs keyless demo, fake-transport tests, paper-gated checks, dashboard checks, and secret scans.

- [ ] **Step 4: Synchronize all copies and run contract tests**

Expected: byte-identical skill copies and all role markers PASS.

- [ ] **Step 5: Commit harness changes with a Lore message**

### Task 4: Full release verification

**Files:**
- Modify if evidence demands: `README.md`, `docs/architecture.md`, `docs/broker-adapters.md`, `docs/agent-prompt-equivalence.md`

**Interfaces:**
- Consumes: all prior implementation plans
- Produces: release evidence and final documentation consistency

- [ ] **Step 1: Run all unit tests**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest discover -s tests -v`

Expected: all PASS.

- [ ] **Step 2: Run compile check**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py analysis.py screening.py data_source.py trading.py feedback.py db.py dashboard.py runtime_config.py notifications.py market_calendar.py brokers`

Expected: success with no syntax errors.

- [ ] **Step 3: Run keyless full demo and safety demos**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache LECTURE_SAVE_REPORTS=0 python3 main.py`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 trading.py --live`

Expected: full mock completion; real broker remains `live_blocked`.

- [ ] **Step 4: Scan secrets, absolute paths, staged files, and ignored artifacts**

Run: `git status --short`

Run: `git diff --cached --name-only`

Run: `rg -n "(DISCORD_WEBHOOK_URL=https://|TELEGRAM_BOT_TOKEN=.+|APP_SECRET=.+|[0-9]{8}-[0-9]{2}|/Users/)" --glob '!docs/superpowers/**' --glob '!tasks/**' .`

Expected: no committed secret value, account number, or personal absolute path.

- [ ] **Step 5: Run code review and visual verdict, fix all high-confidence issues, and rerun the affected evidence**

- [ ] **Step 6: Stage only requested files and create the final Lore commit/PR**
