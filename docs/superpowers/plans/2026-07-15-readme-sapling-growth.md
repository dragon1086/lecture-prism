# README Sapling Growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain `lecture-prism` as a small but extensible system that learners can keep growing with AI after class.

**Architecture:** Add one project-local infographic and one compact README section, then mirror the same message in seminar slide 25 and its speaker script. Keep the existing pipeline and trading safeguards unchanged; verify the documentation contract, standalone HTML, and visual fit.

**Tech Stack:** Markdown, Reveal.js HTML, Python `unittest`, GPT Image built-in generation

## Global Constraints

- Keep the README beginner-first and below 150 lines.
- Do not add terminal command blocks outside the existing coding-agent prompt.
- Generate Korean text directly in the image; do not composite text afterward.
- Do not include secrets, account data, returns, or profit guarantees.
- Do not weaken mock-first or fail-closed live-trading behavior.

---

### Task 1: Lock the growth-message contract

**Files:**
- Modify: `tests/test_readme_outcome_contract.py`
- Modify: `lecture/slides/test_build_single_html.py`

**Interfaces:**
- Consumes: README, source slide, and speaker-script text files
- Produces: assertions for four images, sequential track application, and the sapling-growth message

- [ ] **Step 1: Add assertions for four README images and the growth vocabulary**

Require `docs/assets/readme/system-sapling.png`, `나무 모종`, `매매 로직`, `모니터링`, `대시보드`, `텔레그램·디스코드`, and `한 영역씩` in the relevant source files.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `python3 -m unittest tests.test_readme_outcome_contract lecture.slides.test_build_single_html -v`

Expected: failures for the missing fourth image and sapling wording.

### Task 2: Generate and place the infographic

**Files:**
- Create: `docs/assets/readme/system-sapling.png`

**Interfaces:**
- Consumes: the exact visual structure and Korean labels from the design spec
- Produces: one 16:9 project-local PNG used by README

- [ ] **Step 1: Generate one infographic with the built-in image-generation tool**

Use a dark navy visual system matching the existing README assets. Show roots, trunk, four branches, and a healthy canopy. Require the exact Korean labels from the design and prohibit extra text, watermarks, logos, financial numbers, and profit claims.

- [ ] **Step 2: Copy the selected generated image into the project**

Save the chosen output as `docs/assets/readme/system-sapling.png` without overwriting the three existing images.

- [ ] **Step 3: Inspect the PNG**

Verify every Korean label, the 16:9 composition, readable contrast, and the absence of sensitive information.

### Task 3: Align README, slide, and script

**Files:**
- Modify: `README.md`
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`
- Modify: `lecture/slides/사전오픈_세미나_발표_스크립트.md`

**Interfaces:**
- Consumes: `docs/assets/readme/system-sapling.png`
- Produces: one consistent beginner-facing narrative across all three artifacts

- [ ] **Step 1: Add the README growth section**

Add `수업 뒤에는 직접 키워 갑니다`, the new image, and two short paragraphs explaining the seedling and the four growth directions. Preserve the sequential harness language.

- [ ] **Step 2: Update slide 25**

Use the fifth checklist item to say that learners take home a seedling they can keep growing. Keep the slide at five concise checklist rows.

- [ ] **Step 3: Polish script section 25**

Explain the seedling metaphor in spoken Korean after the KIS path. Mention trading logic, monitoring, dashboard, and Telegram/Discord messages without promising automatic profitability.

- [ ] **Step 4: Run the focused tests**

Run: `python3 -m unittest tests.test_readme_outcome_contract lecture.slides.test_build_single_html -v`

Expected: all focused tests pass.

### Task 4: Rebuild and verify the deliverables

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드_단일파일.html`
- Create or modify: `_workspace/2026-07-15-001/final.md`

**Interfaces:**
- Consumes: final README, source slide, script, and all local images
- Produces: standalone seminar HTML and a Korean-polishing audit artifact

- [ ] **Step 1: Rebuild the standalone HTML**

Run: `python3 lecture/slides/build_single_html.py`

Expected: one HTML file with all slide images embedded as data URLs.

- [ ] **Step 2: Run the complete test suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 3: Verify runtime safety remains intact**

Run: `python3 main.py`

Expected: the mock-first pipeline completes without API keys.

Run: `python3 trading.py --live`

Expected: `live_blocked` and no real order.

- [ ] **Step 4: Visually inspect slide 25 and the new image**

Confirm no clipping at 1280×720, readable Korean, and a consistent story between the slide and README.

- [ ] **Step 5: Record Korean polishing evidence**

Save the final section-25 text and a concise self-check comment in `_workspace/2026-07-15-001/final.md`.
