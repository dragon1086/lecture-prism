# Pre-open Seminar Reveal.js Remodel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an offline, 20-slide Reveal.js presentation whose narrative connects the instructor's investment problem, data-grounded AI research, operating incidents, operational evidence, and the course's mock-first first run.

**Architecture:** Vendor Reveal.js static distribution files under the deck and replace the standalone stack of fixed sections with Reveal.js horizontal sections. Keep all slide copy and layout in one presentation HTML file, using fragments only for paced evidence reveals and local image paths only for evidence assets.

**Tech Stack:** Static HTML, CSS, vanilla JavaScript, vendored Reveal.js, local PNG/JPEG assets.

## Global Constraints

- The deck must open and navigate without internet access or a build step.
- Use `lecture/slides/vendor/reveal.js/` for Reveal.js runtime assets.
- Use the official Reveal.js configuration: controls, progress, `slideNumber: 'c/t'`, hash, keyboard, touch, overview, and linear navigation.
- Keep the deck at 20 slides, including cover and closing question.
- Do not put account names, account numbers, order IDs, tickers, or raw order payloads into presentation copy or markup.
- Keep dashboard simulations and actual-account results distinct, with a past-performance disclaimer.
- Do not commit the local dashboard or account screenshots to the public repository.

---

### Task 1: Vendor Reveal.js for offline playback

**Files:**
- Create: `lecture/slides/vendor/reveal.js/dist/reveal.css`
- Create: `lecture/slides/vendor/reveal.js/dist/reveal.js`
- Create: `lecture/slides/vendor/reveal.js/dist/theme/black.css`
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: official Reveal.js distribution files.
- Produces: relative paths `vendor/reveal.js/dist/reveal.css`, `vendor/reveal.js/dist/theme/black.css`, and `vendor/reveal.js/dist/reveal.js` usable by the deck with no network.

- [ ] **Step 1: Fetch the Reveal.js package without adding a project dependency**

Run: `npm pack reveal.js --pack-destination /private/tmp/lecture-prism-reveal-pack`

Expected: an npm tarball containing `package/dist/reveal.js`, `package/dist/reveal.css`, and `package/dist/theme/black.css`.

- [ ] **Step 2: Copy the required distribution files into the deck vendor directory**

Run: `mkdir -p lecture/slides/vendor/reveal.js/dist/theme && tar -xzf /private/tmp/lecture-prism-reveal-pack/reveal.js-*.tgz -C /private/tmp/lecture-prism-reveal-pack && cp /private/tmp/lecture-prism-reveal-pack/package/dist/reveal.js lecture/slides/vendor/reveal.js/dist/reveal.js && cp /private/tmp/lecture-prism-reveal-pack/package/dist/reveal.css lecture/slides/vendor/reveal.js/dist/reveal.css && cp /private/tmp/lecture-prism-reveal-pack/package/dist/theme/black.css lecture/slides/vendor/reveal.js/dist/theme/black.css`

Expected: all three local runtime files exist.

- [ ] **Step 3: Verify the vendored runtime files**

Run: `test -s lecture/slides/vendor/reveal.js/dist/reveal.js && test -s lecture/slides/vendor/reveal.js/dist/reveal.css && test -s lecture/slides/vendor/reveal.js/dist/theme/black.css`

Expected: exit status 0.

### Task 2: Replace the document structure with the 20-slide narrative

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: the approved 5-act narrative, existing local evidence image paths, and the DB aggregate values already established for 2026-06-24, 2026-06-26, 2026-07-02~03, and 2026-07.
- Produces: exactly 20 direct child sections below `.reveal > .slides`.

- [ ] **Step 1: Build five narrative acts with chapter dividers**

Use this exact sequence: cover; hook; personal loss story; execution-gap fit; data-to-decision divider; MCP and grounded research; report-to-investment decision; Season 1 to open-source production; operating-reality divider; three operating transitions; order-chase incident; stop-loss/retry incident; evidence divider; dashboard evidence; actual-account evidence; course divider; AI/human roles; open-book course promise; README mock-first first run; closing question.

- [ ] **Step 2: Add causal bridge copy before operational evidence**

Use the bridge `결과가 좋았다는 말만으로는 부족했습니다. 위험을 겪고 나서, 판단과 주문과 결과를 남기기 시작했습니다.` as the evidence divider, immediately after the two incident slides.

- [ ] **Step 3: Add paced fragments only where they improve comprehension**

Use three fragments for each incident's event counts and three fragments for the personal-story timeline. Do not fragment static dividers, dashboard screenshots, or course promise slides.

- [ ] **Step 4: Preserve safety wording**

Keep the dashboard simulation disclaimer and the actual-account past-performance disclaimer directly beside their respective evidence.

### Task 3: Add interaction and presentation styling

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: the local Reveal.js paths from Task 1.
- Produces: clickable, keyboard-accessible, touch-accessible slide navigation with a visible progress bar and current/total slide number.

- [ ] **Step 1: Load Reveal.js assets locally**

Add these exact tags to the deck head/body: `<link rel="stylesheet" href="vendor/reveal.js/dist/reveal.css">`, `<link rel="stylesheet" href="vendor/reveal.js/dist/theme/black.css">`, and `<script src="vendor/reveal.js/dist/reveal.js"></script>`.

- [ ] **Step 2: Initialize Reveal.js with the approved configuration**

Add this initialization after the runtime script:

```js
Reveal.initialize({
  controls: true,
  controlsLayout: 'bottom-right',
  progress: true,
  slideNumber: 'c/t',
  hash: true,
  keyboard: true,
  touch: true,
  overview: true,
  navigationMode: 'linear',
  transition: 'fade',
  transitionSpeed: 'fast',
  backgroundTransition: 'fade',
  center: false,
  autoSlide: 0,
});
```

- [ ] **Step 3: Use a presentation-safe custom theme**

Keep the existing deep navy background and purple/teal visual language. Add local CSS for responsive reveal scaling, chapter divider emphasis, cards, evidence image crops, a start-navigation hint, and print layout.

### Task 4: Verify offline playback and content safety

**Files:**
- Test: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: all assets and configuration from Tasks 1-3.
- Produces: evidence that the deck is structurally valid, self-contained, safe in copy, and compatible with the course demo.

- [ ] **Step 1: Verify HTML and the narrative count**

Run: `python3 -c "from html.parser import HTMLParser; import re; p='lecture/slides/사전오픈_세미나_슬라이드.html'; s=open(p,encoding='utf-8').read(); HTMLParser().feed(s); assert len(re.findall(r'<div class=\\\"reveal\\\"><div class=\\\"slides\\\">',s)) == 1; print('HTML parse: OK')"`

Expected: `HTML parse: OK`.

- [ ] **Step 2: Verify runtime and evidence paths**

Run: `rg -n "vendor/reveal.js/dist/(reveal.css|reveal.js|theme/black.css)|assets/(kr-dashboard|us-dashboard|kis-account)" lecture/slides/사전오픈_세미나_슬라이드.html`

Expected: all five local paths appear.

- [ ] **Step 3: Verify copy excludes sensitive raw values**

Run: `rg -n "63513646|ACNT_PRDT_CD|CANO|ORGN_ODNO|PDNO" lecture/slides/사전오픈_세미나_슬라이드.html`

Expected: no matches.

- [ ] **Step 4: Run the demo pipeline**

Run: `python3 main.py`

Expected: mock pipeline completes through screening, analysis, simulation trading, feedback, and dashboard announcement.
