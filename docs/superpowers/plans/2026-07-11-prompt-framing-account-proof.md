# Prompt-Framing and Account-Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first operating-risk slide explain the discovered loss-avoidance framing with authentic, short before/after prompt excerpts, and show the actual-account screenshot without distortion.

**Architecture:** Modify only the standalone Reveal.js deck. Replace numeric cards on the first risk slide with a two-column `before → after` prompt comparison and a plain-language conclusion. Make the account image container center the portrait image with `object-fit: contain` and no transform, preserving its native aspect ratio.

**Tech Stack:** Static HTML, CSS, vanilla JavaScript, vendored Reveal.js, local JPEG evidence asset.

## Global Constraints

- Keep exactly 20 slides and all sources local except the existing GitHub release links.
- Quote only brief, source-verified phrases from the public v1.16.6 and v1.16.7 prompt text.
- Do not claim that an LLM has an innate psychological trait; describe the observed conservative bias as prompt-induced framing.
- Do not add or expose account identifiers, order details, or new personal information.
- Keep the account image at its original aspect ratio with no CSS `transform`.

---

### Task 1: Convert the first risk slide into an explainable prompt-framing case

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html:204-214`

**Interfaces:**
- Consumes: public prompt text confirmed at Prism Insight tags `v1.16.6` and `v1.16.7`.
- Produces: one evidence slide with a concise problem, short before/after excerpts, and a non-technical explanation.

- [x] **Step 1: Replace the three numerical cards with a two-column comparison**

Use short evidence excerpts: `손절이 멀면 진입하지 않는 게 낫다` for the previous framing, and `왜 사면 안 되나` plus `명확한 부정 요소 없으면 진입이 기본` for the revised framing.

- [x] **Step 2: Add an explicit causal explanation**

State that the observation is not an innate LLM trait; repeated loss warnings in the input prompt biased the decision toward non-entry, so the revised prompt requires a concrete reason for non-entry.

- [x] **Step 3: Keep only one plain-language operational proof**

Retain the statement that non-entry decisions accumulated through the strong-market period, without dense record, day, or trade-count figures.

### Task 2: Preserve the actual-account image aspect ratio

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html:114-116`

**Interfaces:**
- Consumes: `lecture/slides/assets/kis-account-2026-07-02.jpeg`.
- Produces: a centered portrait screenshot within the proof card, at its natural aspect ratio and without vertical translation.

- [x] **Step 1: Remove the image crop transform**

Replace `transform: translateY(-208px)` with `transform: none` and use `object-fit: contain` so CSS does not stretch the source JPEG.

- [x] **Step 2: Center the full portrait image**

Set the container to flex centering and set the image to `max-width: 100%`, `height: 100%`, and `width: auto`.

### Task 3: Verify deck structure, visual fit, and demo safety

**Files:**
- Test: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: the modified deck and its local evidence assets.
- Produces: 20-slide static integrity, an in-browser 16:9 preview without overflow, and a completed mock demo pipeline.

- [x] **Step 1: Run static checks**

Run: `git diff --check -- lecture/slides/사전오픈_세미나_슬라이드.html && test "$(rg -c '<section class=\"slide' lecture/slides/사전오픈_세미나_슬라이드.html)" = 20`

Expected: exit status 0.

- [x] **Step 2: Render the first-risk and account slides at 1280×720**

Run a local HTTP preview, open `#/9` and `#/14`, and confirm the present slide has no horizontal or vertical page overflow and the account image does not use a CSS transform.

- [x] **Step 3: Run the mock course pipeline**

Run: `python3 main.py`

Expected: screening, analysis, simulation trading, feedback, and dashboard announcement all complete.
