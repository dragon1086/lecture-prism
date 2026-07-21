# Current Architecture Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make learner-facing documentation and maintained architecture visuals accurately describe the current two-path lecture-prism architecture and its safety contracts.

**Architecture:** Preserve the root mock/real-data teaching pipeline as the first-success route, then introduce `prism_core` classroom/backtest/paper/live work as the stateful operating path. Use concise Markdown for exact contracts and five GPT Image 2 raster infographics for navigable, high-density visual orientation. Document tests protect the safety claims and the generated assets’ presence without changing runtime behavior.

**Tech Stack:** Markdown, Python `unittest`, checked-in PNG assets generated with GPT Image 2, existing standard-library default demo.

## Global Constraints

- Do not change runtime, broker, database, or strategy behavior.
- `python3 main.py` must remain keyless and dependency-free on the demo path.
- Do not add Python/package dependencies.
- Keep learner documentation prompt-oriented; do not add terminal command blocks to README, START_HERE, `docs/`, or exercise guides.
- Treat `mock`/`real_data` fallback separately from `paper`/`live` fail-closed provider behavior.
- State that KIS and Toss lifecycle coverage is fixture-tested, not actual-account E2E tested.
- Preserve real-order dual gating and never print or commit secrets.
- Retain `docs/assets/prism-insight/` as original-system reference assets.

---

### Task 1: Lock the current documentation contract

**Files:**
- Create: `tests/test_documentation_architecture_contract.py`
- Modify: `tests/test_readme_outcome_contract.py`

**Interfaces:**
- Consumes: Markdown files under repository root, `docs/`, and `lecture/exercises/`.
- Produces: fast, file-only regression checks for learner-facing architecture claims and PNG asset existence.

- [ ] **Step 1: Write the failing document-contract test**

```python
class DocumentationArchitectureContractTest(unittest.TestCase):
    def test_docs_describe_two_paths_and_rule_llm_boundary(self):
        combined = "\n".join(read(path) for path in REQUIRED_DOCUMENTS)
        for phrase in (
            "기본 학습 경로",
            "상태 기반 고급 경로",
            "LLM은 BUY를 HOLD로만",
            "fixture",
            "실제 계좌 E2E",
        ):
            self.assertIn(phrase, combined)

    def test_maintained_infographics_exist_as_pngs(self):
        for asset in MAINTAINED_ASSETS:
            self.assertTrue(asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
```

- [ ] **Step 2: Run the new test to verify the old documents fail**

Run: `python3 -m unittest tests.test_documentation_architecture_contract -v`

Expected: FAIL because the baseline documentation has no unified two-path language. Existing PNG files remain valid assets until their GPT Image 2 replacements are generated.

- [ ] **Step 3: Extend the README contract without coupling it to dated slide wording**

```python
def test_readme_names_the_two_learning_paths_and_full_lifecycle(self):
    for phrase in (
        "기본 학습 경로",
        "상태 기반 고급 경로",
        "매수·매도·조회·취소·재시작 reconcile",
    ):
        self.assertIn(phrase, self.readme)
```

- [ ] **Step 4: Run focused tests and confirm the expected pre-documentation failure**

Run: `python3 -m unittest tests.test_documentation_architecture_contract tests.test_readme_outcome_contract -v`

Expected: architecture assertions fail; existing keyless-start and four-track assertions stay green.

### Task 2: Refresh the learner entry points and exercises

**Files:**
- Modify: `README.md`
- Modify: `START_HERE.md`
- Modify: `lecture/exercises/part3_실습가이드.md`
- Modify: `lecture/exercises/part4_실습가이드.md`

**Interfaces:**
- Consumes: current `runtime_config.py`, `main.py`, `analysis.py`, `screening.py`, and `trading.py` behavior.
- Produces: a beginner-safe reader journey from keyless demo to strategy edits, classroom evidence, or optional integrations.

- [ ] **Step 1: Make README terminology match the current public contract**

Replace KIS buy-only promises with a concise lifecycle statement: KIS and optional Toss support BUY/SELL, status lookup, cancellation, and restart reconciliation; uncertain results become `UNKNOWN` and block repeat orders. Keep the first-run paragraph exclusively about the keyless demo. Add an architecture reference link alongside the existing start, exercise, profile, and broker links.

- [ ] **Step 2: Add an explicit post-first-run fork in START_HERE**

Add three prompt-oriented choices after the first success: root A/B/C/D strategy work, fixed offline classroom evidence, or optional real-data/OAuth/broker diagnostics. State that actual ordering is not part of the first-run path.

- [ ] **Step 3: Correct Part 3 status and Part 4 ownership/scope language**

Change Part 3’s OAuth heading from “후속 과제” to an implemented optional exercise and say it performs one qualitative structured call. In Part 4, distinguish root `screening.py` Track A from optional `prism_core/screening.py` detailed screening, and replace “기술·뉴스·전략 LLM 에이전트” with technical/news qualitative interpretation plus rule-owned decision values and risk veto.

- [ ] **Step 4: Run targeted text checks and document tests**

Run: `rg -n '후속 과제|기술·뉴스·전략.*LLM|KIS.*매수 주문' README.md START_HERE.md lecture/exercises docs`

Expected: remaining matches describe only explicitly historical/reference materials or open dashboard work, not the updated learner contracts.

Run: `python3 -m unittest tests.test_documentation_architecture_contract tests.test_readme_outcome_contract tests.test_prism_core_foundation_contract -v`

Expected: PASS.

### Task 3: Consolidate the technical reference documents

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `docs/api-keys.md`
- Modify: `docs/broker-adapters.md`
- Modify: `docs/defaults-and-philosophy.md`
- Modify: `docs/why-multi-agent.md`

**Interfaces:**
- Consumes: current profile definitions, one-call OAuth implementation, broker adapters, and existing historical-reference material.
- Produces: mutually consistent operational and teaching explanations with explicit safety limits.

- [ ] **Step 1: Promote the two runtime paths in architecture and runtime references**

Move the root pipeline to the “foundation path” description and introduce the stateful path before detailed tables. Correct runtime profile wording so classroom/backtest and mock/real-data distinctions appear before paper/live operational behavior. Replace the stale “lifecycle follow-up” row and phrase KIS/Toss status as implementation plus fixture verification, not live-account proof.

- [ ] **Step 2: Align integration, defaults, and multi-agent language with code ownership**

Describe the official Codex route as optional qualitative input, `LLM` veto-only boundaries, `tossctl` WTS limitations, and the distinct real-account gate. Correct the root demo universe language, make root risk constants distinct from `prism_core` regime policy, and recast the original system’s multi-agent chaining as reference rather than active lecture behavior.

- [ ] **Step 3: Label original PRISM links as historical/reference architecture**

In `docs/architecture.md`, keep the original PRISM links but state they explain the upstream system and are not the active lecture runtime. Do not alter the reference source documents or images.

- [ ] **Step 4: Run architecture/rules tests**

Run: `python3 -m unittest tests.test_analysis_runtime_config tests.test_prism_core_foundation_contract tests.test_documentation_architecture_contract -v`

Expected: PASS.

### Task 4: Replace maintained architecture visuals with GPT Image 2 assets

**Files:**
- Modify: `docs/assets/readme/strategy-to-kis.png`
- Modify: `docs/assets/readme/system-result.png`
- Modify: `docs/assets/readme/runtime-architecture-map.png`
- Modify: `docs/assets/readme/module-guide.png`
- Modify: `docs/assets/readme/optional-integrations-safety.png`

**Interfaces:**
- Consumes: exact concepts and short labels from the approved design; no screenshot, token, or account input.
- Produces: five high-contrast Korean educational infographics that retain the existing filenames consumed by README and `docs/architecture.md`.

- [ ] **Step 1: Generate the course and lifecycle visual pair with GPT Image 2**

Generate `strategy-to-kis.png` as a journey map and `system-result.png` as a rule/LLM/order/ledger lifecycle map. Require short Korean labels only, a 16:9 information grid, strong contrast, large typography, `UNKNOWN` as a stop state, and no claims of actual-account E2E.

- [ ] **Step 2: Generate the profile, ownership, and safety visual trio with GPT Image 2**

Generate the three architecture assets as separate high-density Korean infographics. The profile map includes all seven profiles; the ownership map distinguishes root modules from `prism_core`; the safety map includes optional official Codex OAuth, KIS/Toss, fail-closed, and the dual live gate.

- [ ] **Step 3: Inspect every generated PNG at source resolution**

Run: `file docs/assets/readme/{strategy-to-kis,system-result,runtime-architecture-map,module-guide,optional-integrations-safety}.png`

Expected: each file is a readable PNG at a landscape resolution suitable for Markdown rendering.

Use the image viewer on each asset. Reject any image with cut-off text, unreadable Korean glyphs, logos, fabricated broker UI, “profit guaranteed” messaging, or a claim that live-account E2E was performed.

- [ ] **Step 4: Run asset and link checks**

Run: `python3 -m unittest tests.test_documentation_architecture_contract tests.test_readme_outcome_contract -v`

Expected: PASS.

### Task 5: Perform an independent documentation-to-code review and final verification

**Files:**
- Modify only if review finds a documentation or test defect.

**Interfaces:**
- Consumes: all changed documentation, visual assets, current runtime/analysis/broker source, and test results.
- Produces: evidence that public claims still match the implemented contracts.

- [ ] **Step 1: Read the changed documents against source contracts**

Compare profile wording to `runtime_config.py` and `main.py`; compare LLM wording to `analysis.py`; compare lifecycle wording to `trading.py`, `brokers/kis.py`, and `brokers/toss.py`. Record any mismatch and correct the document, not the implementation, unless the source contradicts its own tests.

- [ ] **Step 2: Run the full quality gate**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

Run: `python3 main.py`

Expected: the no-key mock pipeline completes and writes only ignored runtime artifacts.

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m compileall main.py analysis.py screening.py trading.py feedback.py db.py dashboard.py`

Expected: successful compilation without repository `__pycache__` output.

- [ ] **Step 3: Check source hygiene before commit**

Run: `git diff --check && git status --short && git diff --cached --name-only`

Expected: only the planned documentation, PNG assets, and document-contract tests are included; no `.env`, token, account, database, report, or log files are staged.

- [ ] **Step 4: Commit the reviewed refresh with Lore trailers**

```text
Explain the current system without overstating broker readiness

Constraint: Keyless mock teaching path and dual real-order gates remain mandatory
Rejected: Rewrite original PRISM reference assets | they document the upstream system
Confidence: high
Scope-risk: narrow
Directive: Keep fixture verification distinct from real-account E2E claims
Tested: document contracts, complete unit suite, keyless main smoke, image inspection
Not-tested: external KIS/Toss account execution
```
