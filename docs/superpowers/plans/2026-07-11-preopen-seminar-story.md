# Pre-open Seminar Story Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the pre-open seminar deck with the instructor's investment story, operational evidence, and beginner-first course promise.

**Architecture:** Keep the existing standalone 1280×720 HTML deck and its visual system. Replace only the message blocks that establish the opening story, add locally bundled evidence images, and convert the current evidence TODO slide into two proof slides that distinguish simulated dashboards from the actual account result.

**Tech Stack:** Static HTML, CSS, inline SVG, PNG/JPEG assets.

## Global Constraints

- Preserve the existing standalone HTML format and 1280×720 slide canvas.
- Do not add JavaScript libraries or external dependencies.
- Store presentation images under `lecture/slides/assets/` and use relative paths.
- Do not expose account name, owner name, account number, token, or other financial identifiers.
- State 2026-07-10 for dashboard snapshots and distinguish simulated from actual-account results.
- Include a past-performance disclaimer beside the proof slides.

---

### Task 1: Bundle and safely display evidence assets

**Files:**
- Create: `lecture/slides/assets/us-dashboard-2026-07-10.png`
- Create: `lecture/slides/assets/kr-dashboard-2026-07-10.png`
- Create: `lecture/slides/assets/kis-account-2026-07-02.jpeg`
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html`

**Interfaces:**
- Consumes: the three user-provided screenshot files.
- Produces: stable relative image URLs for proof slides.

- [ ] **Step 1: Copy the supplied screenshots into the deck asset directory**

Run: `mkdir -p lecture/slides/assets && cp /Users/aerok/Desktop/미국주식\ 후익률\ 대시보드.png lecture/slides/assets/us-dashboard-2026-07-10.png && cp /Users/aerok/Desktop/한국주식\ 후익률\ 대시보드.png lecture/slides/assets/kr-dashboard-2026-07-10.png && cp /Users/aerok/Desktop/계좌항태_0702.jpeg lecture/slides/assets/kis-account-2026-07-02.jpeg`

Expected: three image files exist below `lecture/slides/assets/`.

- [ ] **Step 2: Add proof-image layout rules**

Add CSS rules for a two-up dashboard image grid, a fixed-height account-proof crop with `overflow: hidden`, and a muted evidence disclaimer. The account crop must position the image below the account-name header.

- [ ] **Step 3: Verify local asset links**

Run: `test -f lecture/slides/assets/us-dashboard-2026-07-10.png && test -f lecture/slides/assets/kr-dashboard-2026-07-10.png && test -f lecture/slides/assets/kis-account-2026-07-02.jpeg`

Expected: exit status 0.

### Task 2: Rebuild the opening narrative

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html:206-270`

**Interfaces:**
- Consumes: the instructor-provided 2018-to-present narrative.
- Produces: opening slides that make the later operational proof relevant.

- [ ] **Step 1: Replace the opening promise with the restaurant-review hook**

Use the headline `밥집은 리뷰 100개 보고 고르면서, 주식은 오늘 기분으로 사셨나요?` and position it as the first content slide after the cover.

- [ ] **Step 2: Add the personal execution-gap story**

Add a concise timeline: 2018 investment start; books and reading rooms; a profitable COVID period; later losses; and the practical constraints of work and childcare.

- [ ] **Step 3: Make system-trading fit explicit**

Use three cards for people who have a strategy but are emotional in execution, cannot monitor charts in real time, or change their criteria between similar situations.

- [ ] **Step 4: Verify copy does not promise returns**

Run: `rg -n '보장|확실한 수익|무조건' lecture/slides/사전오픈_세미나_슬라이드.html`

Expected: no claims that promise or guarantee investment returns.

### Task 3: Connect operating work to verifiable evidence

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html:254-505`

**Interfaces:**
- Consumes: asset URLs from Task 1 and performance figures in the approved design.
- Produces: separate dashboard and account-evidence slides.

- [ ] **Step 1: Update the project-origin metrics**

Describe the maternity-leave AI discovery, 350+ Telegram/Claude Code improvements, 90 deployments, GitHub 650 stars, and Telegram community of 820 without conflating deployment count with release count.

- [ ] **Step 2: Replace the evidence TODO slide with dashboard evidence**

Add the Korea and US dashboard images together, label both `2026.07.10 기준`, and state the displayed simulated returns and MDD separately from their benchmarks.

- [ ] **Step 3: Add actual-account evidence as a separate slide**

Display only the safe account crop with `2025.10~2026.07`, `투자손익 6,211,266원`, and `수익률 24.86%`. Add `과거 실계좌 결과이며 미래 수익을 보장하지 않습니다.`

- [ ] **Step 4: Verify asset references and account crop structure**

Run: `rg -n 'assets/(us-dashboard|kr-dashboard|kis-account)|과거 실계좌' lecture/slides/사전오픈_세미나_슬라이드.html`

Expected: all three asset paths and the disclaimer are present.

### Task 4: Close on the learner's first successful run

**Files:**
- Modify: `lecture/slides/사전오픈_세미나_슬라이드.html:557-621`

**Interfaces:**
- Consumes: lecture-prism's mock-first, API-key-free teaching constraints.
- Produces: an unambiguous transition from proof to course action.

- [ ] **Step 1: Add the AI-coding boundary**

State that people own strategy, observation, and judgment criteria while AI assists implementation, revision, and verification.

- [ ] **Step 2: Make the README taste concrete**

State the learner path: API-key-free demo completion, then change one of entry, analysis, exit, or risk rules to express a personal strategy.

- [ ] **Step 3: Render and visually inspect the deck**

Open the local HTML in a browser or render it to confirm that the opening hook, dashboard pair, account crop, and final course slide fit the 1280×720 canvas without clipped text or exposed identifying data.

- [ ] **Step 4: Verify the final source and worktree scope**

Run: `git diff -- lecture/slides/사전오픈_세미나_슬라이드.html && git status --short`

Expected: only the slide deck, its new assets, and workflow-planning documents are newly changed by this task; pre-existing README and exercise-guide changes remain untouched.
