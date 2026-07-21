# Official Codex OAuth Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final independent-review findings without weakening the keyless demo, deterministic trade gates, or official Codex login path.

**Architecture:** Keep `llm_provider.py` as the only external LLM boundary and `analysis.run_analysis()` as the only active orchestration path. Fail closed when Codex CLI configuration drifts, pass only credential-free proxy plumbing, remove the unused quantitative LLM path, and align learner-facing documentation with the official Codex route.

**Tech Stack:** Python 3.10+ standard library, `asyncio` subprocesses, `unittest`, Markdown/HTML documentation.

## Global Constraints

- `python3 main.py` must complete without API keys or optional packages.
- LLM output may only add prose or veto an existing quantitative BUY.
- No new required dependency.
- No real broker order, credential read, or existing `prism.db` mutation during verification.
- Preserve the legacy `PRISM_OPENAI_AUTH_MODE=chatgpt_oauth` flag only as an explicit compatibility selector for official Codex; never start `cores/chatgpt_proxy`.

---

### Task 1: Harden the Codex subprocess boundary

**Files:**
- Modify: `llm_provider.py`
- Test: `tests/test_llm_provider.py`

**Interfaces:**
- Consumes: `CodexSubscriptionProvider.complete(system_prompt: str, user_message: str) -> str`
- Produces: `_codex_environment() -> dict[str, str]` that excludes credential-bearing proxy URLs and an argv contract that fails on unknown configuration.

- [x] **Step 1: Write failing subprocess-boundary tests**

Add assertions that `--strict-config` and `--ignore-rules` are present, and add:

```python
def test_environment_rejects_proxy_urls_with_userinfo(self):
    with mock.patch.dict(
        os.environ,
        {
            "HTTPS_PROXY": "http://user:secret@example.test:8080",
            "HTTP_PROXY": "http://proxy.example.test:8080",
        },
        clear=True,
    ):
        child_env = llm_provider._codex_environment()
    self.assertNotIn("HTTPS_PROXY", child_env)
    self.assertEqual(child_env["HTTP_PROXY"], "http://proxy.example.test:8080")
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_llm_provider -v`

Expected: failures for missing strict/rules flags and credential-bearing proxy inclusion.

- [x] **Step 3: Implement the minimum boundary changes**

Use `urllib.parse.urlsplit()` for proxy keys only; omit a proxy value when `username` or `password` is present. Add `--strict-config` and `--ignore-rules` to the Codex argv before feature overrides.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `python3 -m unittest tests.test_llm_provider -v`

Expected: all provider tests pass.

---

### Task 2: Remove the dormant quantitative LLM path

**Files:**
- Modify: `analysis.py`
- Test: `tests/test_analysis_runtime_config.py`

**Interfaces:**
- Consumes: `run_analysis(ticker: str) -> dict`
- Produces: one active LLM call through `_run_combined_llm_agent()` and no `_run_strategy_agent`, `_run_technical_agent`, or `_run_news_agent` alternate call paths.

- [x] **Step 1: Write a failing legacy-path regression test**

```python
def test_legacy_multi_call_helpers_are_not_exposed(self):
    for name in ("_run_technical_agent", "_run_news_agent", "_run_strategy_agent"):
        self.assertFalse(hasattr(analysis, name), name)
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_analysis_runtime_config.AnalysisRuntimeConfigTest.test_legacy_multi_call_helpers_are_not_exposed -v`

Expected: failure naming the first legacy helper.

- [x] **Step 3: Delete unused helpers and the quantitative strategy prompt**

Remove `STRATEGY_AGENT_PROMPT` and all three unused `_run_*_agent` functions. Keep `TECHNICAL_AGENT_PROMPT` and `NEWS_AGENT_PROMPT` because `COMBINED_AGENT_PROMPT` embeds them for the Part 4 prompt track. Update `_llm_enabled()` documentation to describe explicit official providers.

- [x] **Step 4: Run analysis and trading safety tests**

Run: `python3 -m unittest tests.test_analysis_runtime_config tests.test_trading_decision_safety -v`

Expected: all tests pass and the one-call/veto-only tests remain green.

---

### Task 3: Align current-facing documentation

**Files:**
- Modify: `START_HERE.md`
- Modify: `requirements.txt`
- Modify: `docs/architecture.md`
- Modify: `docs/agent-prompt-equivalence.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `docs/superpowers/specs/2026-07-20-official-codex-subscription-provider-design.md`
- Modify: `lecture/curriculum.html`
- Modify: `lecture/exercises/part4_실습가이드.md`
- Test: `tests/test_prism_core_foundation_contract.py`

**Interfaces:**
- Consumes: official Codex OAuth behavior already implemented by `llm_provider.py`
- Produces: learner-facing text that never routes the current lecture pipeline through localhost:18741 or `cores/chatgpt_proxy`.

- [x] **Step 1: Add a failing current-doc contract**

Read the current architecture, curriculum, requirements comments, and Part 4 exercise, then assert that active guidance uses `llm_provider.py`/`LECTURE_LLM_MODE=oauth` and does not instruct use of localhost:18741 or `_run_news_agent`.

- [x] **Step 2: Run the documentation contract and verify RED**

Run: `python3 -m unittest tests.test_prism_core_foundation_contract -v`

Expected: failure on at least one stale current-facing path.

- [x] **Step 3: Update documentation without rewriting original-system reference docs**

Point current lecture architecture at `llm_provider.py`, label `cores/chatgpt_proxy` as retained reference/regression code, replace current curriculum proxy instructions with official Codex login guidance, replace `_run_news_agent` exercise guidance with `NEWS_AGENT_PROMPT` or the provider evidence boundary, and document the explicit legacy environment selector.

- [x] **Step 4: Run documentation tests and stale-path scans**

Run: `python3 -m unittest tests.test_prism_core_foundation_contract tests.test_strategy_harness_contract -v`

Expected: all tests pass. `rg` may still find proxy terms only in clearly labeled original/reference code and its regression tests.

---

### Task 4: Reverify and obtain independent approval

**Files:**
- Verify all files in the OAuth diff.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: complete verification evidence and independent code/architecture verdicts.

- [x] **Step 1: Run focused and full verification**

Run the provider/analysis/trading tests, full unittest discovery, temp-DB mock pipeline, compileall, `git diff --check`, and secret/local-path scans.

- [x] **Step 2: Re-run both independent read-only review lanes**

Require code-reviewer `APPROVE` with no Critical/High findings and architect `CLEAR`. If either lane blocks or watches, fix and repeat.

- [x] **Step 3: Stage only the reviewed OAuth unit**

Check `git status --short` and `git diff --cached --name-only`; exclude `.env`, secrets, databases, reports, logs, tasks, and local paths.

- [x] **Step 4: Create one Lore commit**

Use an intent-first message with `Constraint`, `Rejected`, `Confidence`, `Scope-risk`, `Directive`, `Tested`, and `Not-tested` trailers.
