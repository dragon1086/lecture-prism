# Part 3 Learner Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework Part 3 so every module starts with a learner problem, uses a deterministic example, and ends with an application question tied to the learner's own strategy.

**Architecture:** Keep the existing 38-slide modular HTML deck and its build pipeline. Replace copy and one cover visual without changing Python behavior, then lock the learning sequence with document contract tests and verify the generated HTML at 1600×900.

**Tech Stack:** Static HTML/CSS, Markdown, Node.js deck builder, Python `unittest`, built-in image generation, headless Chrome and Poppler.

## Global Constraints

- Part 3 remains 38 slides and Part 4 remains 40 slides.
- Python execution behavior, safety gates, Part 4 prompts, and student knowledge boundaries do not change.
- The cover image contains no text, logo, ticker chart, emoji, or watermark.
- All module examples come from repository fixtures or tests; no current-market claim is invented.
- Students think about a strategy change in Part 3 but edit code only in Part 4.
- Existing user-owned `_workspace/` directories and unrelated changes are not staged or modified.

---

### Task 1: Lock the learner-facing contract

**Files:**
- Modify: `tests/test_part3_deck_contract.py`
- Modify: `tests/test_part3_student_learning_contract.py`

**Interfaces:**
- Consumes: Part 3 module HTML files and the student prompt Markdown.
- Produces: Failing contracts for the cover asset, P3-01 navigation, 12 application questions, the operations closing image, and the application-oriented final slide.

- [ ] **Step 1: Replace the old slide 34-only contract with the new closing and cover contract**

Add assertions that:

```python
self.assertIn("assets/part3-cover-ai-console.png", self.sources)
self.assertIn("P3-01 · API 키 없는 첫 성공", self.sources)
self.assertEqual(self.sources.count("prism-auxiliary-operations-loop.png"), 1)
self.assertNotIn("최근 90일 거래 기록", slide_34)
self.assertIn("기억은 많이 쌓는 것보다", slide_34)
self.assertIn("오늘 바로 바꿔 볼 한 가지", self.sources)
```

- [ ] **Step 2: Add the 12-question synchronization contract**

Define the exact 12 Korean questions from the design spec and assert each appears in both the deck sources and `수강생_붙여넣기_프롬프트_파트3.md`. Assert all four module blocks contain `마지막에는 내가 답할 아래 질문 세 개를 질문만 남겨줘` or an equivalent fixed phrase that forbids the agent from answering.

- [ ] **Step 3: Run the focused tests and verify the red phase**

Run:

```bash
python3 -m unittest \
  tests.test_part3_deck_contract \
  tests.test_part3_student_learning_contract -v
```

Expected: failures for the missing cover asset reference, P3-01 visible navigation, new questions, closing image location, and application final slide.

### Task 2: Replace the cover visual and clarify the first prompt

**Files:**
- Create: `강의자료/assets/part3-cover-ai-console.png`
- Modify: `강의자료/deck-src/part3/00-opening.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `강의자료/deck-src/part3-index.md`

**Interfaces:**
- Consumes: Existing Part 3 dark cover palette and exact title copy.
- Produces: A text-free 16:9 cover background asset and a P3-S04 instruction that names the exact student prompt section.

- [ ] **Step 1: Generate the cover background**

Use the built-in image generator with a 16:9 composition: near-black midnight navy, upper 60% quiet negative space, lower 35–40% glass-and-metal AI system console, violet signals flowing into teal, soft cinematic light, edges dissolving into the background. Explicitly forbid text, logos, ticker charts, emojis, borders, floating cards, watermarks, people, and trading-floor clichés.

- [ ] **Step 2: Inspect and save the selected output in the project**

Inspect the generated image at original resolution. Copy the selected final output to `강의자료/assets/part3-cover-ai-console.png` without overwriting another asset.

- [ ] **Step 3: Replace the inline cover SVG**

Remove the P3-S01 `<svg>` and insert the generated image as a full-slide decorative background or lower-layer image while keeping the existing kicker, title, byline, and page number as HTML text.

- [ ] **Step 4: Rewrite P3-S04 navigation**

Show this exact instruction in the visible flow:

```text
수강생 붙여넣기 프롬프트 파일에서
‘P3-01 · API 키 없는 첫 성공’을 찾고,
‘코딩 에이전트에 붙여넣기’ 블록 전체를 복사합니다.
```

Update the manifest and index only if the P3-S04 title changes.

### Task 3: Turn module checks into learner application

**Files:**
- Modify: `강의자료/deck-src/part3/02-context.html`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`
- Modify: `강의자료/강사용_실습진행_스크립트.md`

**Interfaces:**
- Consumes: Exact 12 questions and four deterministic examples from the design spec.
- Produces: Synchronized slide, instructor, and student-prompt learning loops for modules 1–4.

- [ ] **Step 1: Add a visible problem question at each module opening**

Use the four exact problem questions from the design spec in the opening slide title or a large learner-facing prompt. Keep the original architecture image large and move the factual title into the kicker or caption when necessary.

- [ ] **Step 2: Replace `확인 1·2·3` on P3-S13, S20, S29, and S36**

Use `내 전략에 대입 1·2·3` and the exact three questions for that module. Shorten wording only if required for fit without changing meaning.

- [ ] **Step 3: Add three unanswered questions to every module prompt**

At the end of each P3-M1–M4 code block, instruct the coding agent to leave the exact three questions unanswered. Preserve the rules that code is not edited and real orders, broker accounts, API keys, and secrets are not used.

- [ ] **Step 4: Add problem, prediction, evidence, and 60-second pair-talk cues to the instructor script**

For each module include:

```text
문제 먼저: [module problem]
20초 예상: 이유를 한 문장으로 적는다.
증거 공개: [fixture/test outcome]
60초 짝 대화: 세 질문 중 하나를 골라 내 전략에 대입해 말한다.
```

When time is short, skip whole-class sharing but keep pair talk.

- [ ] **Step 5: Run focused contracts**

Run:

```bash
python3 -m unittest \
  tests.test_part3_deck_contract \
  tests.test_part3_student_learning_contract -v
```

Expected: the 12 questions and knowledge-boundary contracts pass; closing and generated-asset assertions may remain red until Task 4.

### Task 4: Rebuild the operations closing and application ending

**Files:**
- Modify: `강의자료/deck-src/part3/04-guided-practice.html`
- Modify: `강의자료/deck-src/part3/05-bridge.html`
- Modify: `강의자료/deck-src/part3/99-close.html`
- Modify: `강의자료/deck-src/deck-manifest.json`
- Modify: `강의자료/deck-src/part3-index.md`
- Modify: `강의자료/강사용_실습진행_스크립트.md`

**Interfaces:**
- Consumes: `prism-auxiliary-operations-loop.png` and the already approved operations-closing design.
- Produces: A short P3-S30 transition, memory-management P3-S34, image-led P3-S37 summary, and application-led P3-S38 ending.

- [ ] **Step 1: Convert P3-S30 into a short transition**

Remove `prism-auxiliary-operations-loop.png`. Explain in three steps that the system keeps watching holdings, checks unresolved fills, and prepares completed trades for feedback.

- [ ] **Step 2: Replace P3-S34 statistics with memory hygiene**

Use `기억은 많이 쌓는 것보다 쓸 만하게 유지하는 게 중요합니다` and distinguish recent lessons, repeated lessons, and old or unhelpful lessons. Remove recent-90-day counts and causal-performance discussion.

- [ ] **Step 3: Move the high-density operations image to P3-S37**

Use `split large-diagram`, a large `prism-auxiliary-operations-loop.png`, and a plain-language caption that separates the four main modules from holding monitoring, fill checks, memory compression, and next-entry reference.

- [ ] **Step 4: Replace P3-S38 Q&A with an application sentence**

Display:

```text
오늘 바로 바꿔 볼 한 가지는 무엇입니까?
내 전략에서 ___을 먼저 바꿔 보고 싶다. 이유는 ___이다.
```

Offer four choices: 후보 조건, 분석 역할, 진입과 청산, 기록과 운영. Keep Q&A as a small follow-on note rather than the slide title.

- [ ] **Step 5: Synchronize manifest, index, and instructor closing**

Update P3-S30, P3-S34, P3-S38 titles and replace the old performance-statistics talk track. Add the tomorrow-rehearsal checklist from the design spec to the instructor document.

### Task 5: Build, render, verify, and commit

**Files:**
- Modify generated output: `강의자료/파트3_슬라이드.html`
- Verification only: all changed sources and tests

**Interfaces:**
- Consumes: All source edits and the generated cover asset.
- Produces: A synchronized 38-slide Part 3 deck with verified rendering and repository evidence.

- [ ] **Step 1: Build the decks**

Run:

```bash
node 강의자료/deck-src/build-decks.mjs
```

Expected: `part3: 38 slides`, `part4: 40 slides`.

- [ ] **Step 2: Render representative changed slides at 1600×900**

Print Part 3 to PDF with headless Chrome and extract pages 1, 4, 7, 13, 14, 20, 21, 29, 30, 31, 34, 36, 37, and 38. Inspect every extracted page for title wrapping, small type, overlap, clipping, poor image crop, and unreadable generated text.

- [ ] **Step 3: Apply visual-verdict until the score is at least 90**

Persist the verdict at `.omx/state/part3-learner-activation/ralph-progress.json`. If the score is below 90, fix the named issue and rerender before continuing.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
python3 -m unittest \
  tests.test_part3_deck_contract \
  tests.test_part3_student_learning_contract \
  tests.test_prism_core_foundation_contract -v
LECTURE_PROFILE=mock LECTURE_NOTIFY_DISCORD=0 LECTURE_SAVE_REPORTS=0 python3 main.py
python3 -m unittest discover -s tests -q
git diff --check
```

Expected: all tests pass, mock pipeline completes, and no whitespace errors are reported.

- [ ] **Step 5: Check staged scope and secrets**

Stage only the design-approved files, the cover image, generated Part 3 HTML, and related tests. Verify `git diff --cached --name-only` and scan the staged diff for API keys, tokens, account data, local absolute paths, and private keys.

- [ ] **Step 6: Commit with a Lore message**

Record the learner-activation intent, the 38-slide constraint, rejected slide-count expansion, visual-verdict score, test counts, mock completion, and the remaining live-rehearsal risk.
