# KIS Data Enrichment Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students prove a paper-or-real KIS connection with one read-only Samsung Electronics price/investor-flow snapshot, use that evidence to replace only the weak yfinance supply proxy, and align the Part 3/4 teaching materials and visuals.

**Architecture:** Extend the existing standard-library `KISClient` with a credential-light read-only configuration and normalized daily investor-flow method. A new `kis_market_data.py` boundary composes daily price and investor flow into a dated snapshot; `data_source.py` optionally enriches yfinance data when `LECTURE_SUPPLY_SOURCE=kis`, while default mock/proxy behavior stays unchanged. Course prompts, instructor notes, slides, and generated HTML consume that same contract.

**Tech Stack:** Python 3.10+ standard library, `unittest`, existing HTML slide source/build script, ImageGen PNG asset, Node deck assembler.

## Global Constraints

- `python3 main.py` must still complete without API keys or new required dependencies.
- Never call KIS order, cancel, correction, balance, holdings, orderable-quantity, or account endpoints from the data lab.
- Never enable `LECTURE_ENABLE_LIVE_BROKER`, `LECTURE_ALLOW_REAL_BROKER`, unattended-live acknowledgements, schedules, or service managers.
- Never print or commit App Key, App Secret, access token, account number, `.env`, reports, logs, or `prism.db`.
- The instructor uses KIS real/prod for the Part 4 read-only demonstration; students may explicitly choose paper or real.
- A failed P3-04 check must remain a visible KIS failure; only Part 4 analysis enrichment may fall back once to the existing volume proxy.
- Weekend/holiday output must show the response business date and must not call the value real-time.
- Student-facing documentation provides prompts for coding agents, not terminal command blocks.
- Use the Lore commit protocol and verify staged filenames plus secret patterns before every commit.

---

### Task 1: Restore the Known Documentation Baseline

**Files:**
- Modify: `docs/architecture.md`
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: existing Discord notification documentation contract.
- Produces: architecture copy that explicitly names the optional `피드백 저장` notification.

- [ ] **Step 1: Run the existing failing contract**

Run: `python3 -m unittest tests.test_notifications.DiscordDocumentationContractTest.test_example_and_architecture_document_optional_decision_notifications -v`

Expected: FAIL because `docs/architecture.md` does not contain `피드백 저장`.

- [ ] **Step 2: Add the missing observable behavior to the architecture copy**

Change the optional-notification paragraph so its result list includes `피드백 저장` while retaining the statement that Discord failure never blocks trading decisions or DB writes.

- [ ] **Step 3: Verify and commit**

Run the single test again; expect PASS. Commit only `docs/architecture.md` with a Lore message explaining that the baseline contract is restored before KIS work.

---

### Task 2: Add Read-Only KIS Market Contracts

**Files:**
- Modify: `brokers/kis_client.py`
- Modify: `tests/test_kis_client.py`

**Interfaces:**
- Produces: `KISConfig.from_env_market_data(mode: str) -> KISConfig` requiring only the selected environment's App Key and App Secret.
- Produces: `KISClient.get_investor_flow(ticker: str, as_of_date: str) -> list[dict[str, object]]` with `as_of`, `institution_net_buy`, `foreign_net_buy`, `individual_net_buy`, and `source`.
- Preserves: `KISConfig.from_env()` still requires account credentials for broker operations.

- [ ] **Step 1: Write failing configuration and request-contract tests**

Add tests proving `from_env_market_data("paper")` succeeds with only `KIS_PAPER_APP_KEY` and `KIS_PAPER_APP_SECRET`, never reads real credentials, and redacts both values. Add a response fixture with `stck_bsop_date`, `orgn_ntby_qty`, `frgn_ntby_qty`, and `prsn_ntby_qty` and assert the exact GET path `/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily`, TR ID `FHPTJ04160001`, ticker/date parameters, normalized integers, and descending dates.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_kis_client.KISConfigTest tests.test_kis_client.KISClientRequestContractTest -v`

Expected: FAIL because the new classmethod and client method do not exist.

- [ ] **Step 3: Implement the minimal read-only methods**

`from_env_market_data` canonicalizes paper/real, reads only `KIS_<MODE>_APP_KEY` and `KIS_<MODE>_APP_SECRET`, supplies an empty account number internally, and raises a message containing names but no values. `get_investor_flow` validates a six-digit ticker and `YYYYMMDD`, performs one GET, requires a list response, converts signed quantity strings with `int`, converts the date to `YYYY-MM-DD`, sorts newest first, and raises `KISRequestError` on malformed rows.

- [ ] **Step 4: Add malformed/secret-sanitization tests and verify GREEN**

Cover empty output, invalid dates, invalid quantities, provider errors containing credentials, and confirm no request path contains `/trading/`. Run the focused test classes; expect PASS.

- [ ] **Step 5: Commit the client contract**

Stage only `brokers/kis_client.py` and `tests/test_kis_client.py`; secret-scan the staged diff and commit with a Lore message.

---

### Task 3: Build the Read-Only P3-04 Snapshot Boundary

**Files:**
- Create: `kis_market_data.py`
- Create: `tests/test_kis_market_data.py`

**Interfaces:**
- Consumes: `KISConfig.from_env_market_data`, `KISClient.get_daily_prices`, and `KISClient.get_investor_flow`.
- Produces: `fetch_kis_snapshot(ticker: str = "005930", mode: str = "paper", *, client=None, today=None) -> dict`.
- Produces snapshot keys: `environment`, `source`, `ticker`, `as_of`, `price`, `institution_net_buy`, `foreign_net_buy`, `individual_net_buy`, `order_calls`.
- Produces: `format_snapshot(snapshot: dict) -> str` with no secrets and an explicit `주문·취소·계좌 호출 0건` line.

- [ ] **Step 1: Write failing snapshot tests**

Use a fake read-only client that exposes only `get_daily_prices` and `get_investor_flow`. Return multiple dates and assert that `fetch_kis_snapshot` selects the newest common business date, parses `stck_clpr`, reports paper/real exactly, and always returns `order_calls: 0`. Add a no-common-date test that fails closed instead of mixing dates.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_kis_market_data -v`

Expected: FAIL because `kis_market_data.py` does not exist.

- [ ] **Step 3: Implement the minimal snapshot and CLI**

Query a fourteen-calendar-day daily-price window ending at `today`, query investor flow once with the same end date, join by `YYYY-MM-DD`, and return the newest common row. The CLI accepts only `--mode paper|real` and `--ticker`; it prints the formatted snapshot or a sanitized one-line failure and exits nonzero. It never falls back to mock and never imports `trading.py` or a broker adapter.

- [ ] **Step 4: Add failure and mutation-boundary tests**

Assert missing credentials, malformed price rows, provider exceptions containing fake secrets, and fake clients that define order methods but record zero calls. Verify formatted output includes the business date and does not contain token/key/account fixture values.

- [ ] **Step 5: Verify and commit**

Run `python3 -m unittest tests.test_kis_market_data tests.test_kis_client -v`; expect PASS. Compile the two Python files outside the repo pycache. Commit only the snapshot boundary and tests.

---

### Task 4: Enrich Only the Supply Evidence

**Files:**
- Modify: `runtime_config.py`
- Modify: `data_source.py`
- Modify: `analysis.py`
- Modify: `tests/test_runtime_config.py`
- Modify: `tests/test_data_source_modes.py`
- Modify: `tests/test_analysis_agent_boundaries.py`

**Interfaces:**
- Produces: `RuntimeConfig.supply_source: str`, normalized from `LECTURE_SUPPLY_SOURCE=proxy|kis`, default `proxy`.
- Consumes: `kis_market_data.fetch_kis_snapshot` only when the base stock data is not mock and `supply_source == "kis"`.
- Produces KIS supply keys: `source`, `as_of`, `institution_net_buy`, `foreign_net_buy`, `individual_net_buy`.
- Preserves: all existing function signatures and yfinance/mock structures.

- [ ] **Step 1: Write failing runtime and enrichment tests**

Assert default `supply_source == "proxy"`, explicit `kis` normalization, and runtime summary visibility. In data-source tests inject a KIS snapshot and assert only `supply` changes while price, technical, finance, news, and source remain yfinance. Assert KIS is never called for mock mode and one KIS failure leaves the original proxy in place.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_runtime_config tests.test_data_source_modes tests.test_analysis_agent_boundaries -v`

Expected: FAIL on missing `supply_source` and KIS evidence rendering.

- [ ] **Step 3: Implement the runtime switch and enrichment**

Add `supply_source` to every `RuntimeConfig` constructor. In `fetch_stock_data`, fetch the existing base result first; if it is yfinance and KIS is selected, call a small `_enrich_supply_with_kis` helper. On failure log one sanitized warning and return the untouched proxy. Do not retry and do not change `data_source` from `yfinance`.

- [ ] **Step 4: Render KIS evidence in analysis**

Teach `_section_supply` to prefer actual KIS quantities when `supply.source == "kis"`, including the business date. Update section provenance and `data_notice` so only the supply entry says KIS while other entries remain yfinance. Keep the proxy wording unchanged when KIS is absent.

- [ ] **Step 5: Verify and commit**

Run the three focused modules plus `python3 main.py` with ambient KIS enrichment disabled; expect the mock pipeline to complete without network or broker calls. Commit the runtime/data/analysis slice.

---

### Task 5: Rewrite P3-03/P3-04 and Align Course Documentation

**Files:**
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트3.md`
- Modify: `lecture/exercises/수강생_붙여넣기_프롬프트_파트4.md`
- Modify: `강의자료/강사용_실습진행_스크립트.md`
- Modify: `강의자료/수업_시작_전_안내.md`
- Modify: `lecture/curriculum.html`
- Modify: `docs/api-keys.md`
- Modify: `docs/runtime-profiles.md`
- Modify: `docs/architecture.md`
- Modify: `tests/test_part3_student_learning_contract.py`
- Modify: `tests/test_operations_documentation_contract.py`

**Interfaces:**
- P3-03 consumes last successful step, expected/actual result, and complete error excerpt; it produces evidence, minimal change, rerun result, and remaining risk.
- P3-04 invokes `kis_market_data.py` through the coding agent with an explicit paper/real choice and no terminal instructions for the student.
- Part 4 common lab consumes the P3-04 snapshot and enables `LECTURE_SUPPLY_SOURCE=kis` only for the demonstrated analysis execution.

- [ ] **Step 1: Write failing documentation contracts**

Assert P3-03 no longer contains the prewritten taxonomy `Yahoo 429`/`DNS`/`선택 패키지`, but contains the three evidence inputs, `관련 파일만 최소한`, and `같은 실행을 다시 검증`. Assert P3-04 contains `KIS`, `paper`, `real`, `005930`, 가격, 기관·외국인·개인, 기준일, no mock masquerade, no automatic retry, and zero order/account calls.

- [ ] **Step 2: Verify RED and rewrite the prompts**

Run the focused documentation tests and confirm expected failures. Replace the current P3-03 and yfinance P3-04 blocks with concise natural prompts matching the approved design; keep student reflection sentences and success evidence concrete.

- [ ] **Step 3: Align instructor, start guide, curriculum, and reference docs**

Add the P3-04 smoke-test teaching beat, real/prod instructor demonstration, paper-or-real student path, weekend business-date wording, and Part 4 supply replacement. Remove claims that no KIS setting is read anywhere in Part 3, while retaining zero trading/account endpoint rules and manual local secret entry.

- [ ] **Step 4: Verify and commit**

Run the focused documentation contracts and secret/local-path scan. Commit the prompt/document slice.

---

### Task 6: Create the Dense Part 3 Visual and Update Part 3/4 Slides

**Files:**
- Create: `강의자료/assets/prism-data-enrichment-lab.png`
- Modify: `강의자료/deck-src/part3/03-system-map.html`
- Modify: `강의자료/deck-src/part4/00-foundation.html`
- Regenerate: `강의자료/deck-src/part3-index.md`
- Regenerate: `강의자료/deck-src/part4-index.md`
- Regenerate: `강의자료/파트3_슬라이드.html`
- Regenerate: `강의자료/파트4_슬라이드.html`
- Modify: `tests/test_part3_deck_contract.py`
- Create: `tests/test_part4_deck_contract.py`

**Interfaces:**
- The new PNG communicates sources → validation/normalization → connection methods → report sections.
- P3-S22 uses the PNG plus HTML copy that repeats critical labels and previews P3-04/Part 4.
- P4-S04 becomes the common KIS read-only data-enrichment beat before P4-S05 introduces A/B/C/D tracks, preserving all existing slide IDs and the 39-slide count.

- [ ] **Step 1: Load presentation/image instructions and inspect references**

Read the full Presentations and imagegen skills, load workspace dependencies, inspect `prism-analysis-agent-map.png` and `prism-analysis-prompt-quant.png`, and record the exact 16:9 composition, palette, type hierarchy, and crop needs.

- [ ] **Step 2: Generate and inspect the 1920×1080 asset**

Use ImageGen for a warm-ivory futuristic analysis laboratory with silver/glass machinery and blue/purple/teal/orange flows. Keep image text to short labels: `KIS API`, `웹·크롤링`, `파일·DB`, `yfinance`, `검증·정규화`, `직접 HTTP`, `어댑터`, `MCP`, `기술`, `수급`, `재무`, `뉴스`, `시장`. Inspect at original resolution and regenerate if labels, crop, or visual hierarchy fail.

- [ ] **Step 3: Write failing slide contracts and update sources**

Require the new asset, MCP-not-source explanation, KIS P3-04 preview, and P4-S04 real/prod read-only demonstration copy. Replace the redundant P4-S04 divider with the common KIS lab while preserving the existing visual system and avoiding low-value card density.

- [ ] **Step 4: Assemble and render**

Run `node 강의자료/deck-src/build-decks.mjs`. Use the existing HTML rendering/inspection path to render all changed slides at 1280×720, inspect each full-size, and fix clipping, overlap, wrapping, and unreadable image crops.

- [ ] **Step 5: Verify and commit**

Run Part 3/4 deck contracts, assert the PNG is 1920×1080, and scan generated HTML/assets for secrets and local paths. Commit source, generated decks, indices, tests, and final PNG together.

---

### Task 7: Full Safety and Completion Verification

**Files:**
- Verify all changed files; do not introduce new implementation files.

**Interfaces:**
- Proves the complete approved design without using real credentials or sending external broker mutations.

- [ ] **Step 1: Run safe execution checks**

Run `python3 main.py`, `python3 trading.py --live`, and the P3-04 smoke-test unit fixtures. Confirm main completes in simulation, live returns `live_blocked`, and order/cancel/account call counts remain zero.

- [ ] **Step 2: Run compile and full tests**

Run compileall with `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache`, then `python3 -m unittest discover -s tests -v`. Require zero failures after Task 1 restores the known baseline.

- [ ] **Step 3: Inspect repository scope and secrets**

Run `git status --short`, `git diff --check`, staged filename review, and scans for API/token/account values, `.env`, local absolute paths, reports, logs, DBs, and KIS auth files. Confirm the preserved stash is untouched.

- [ ] **Step 4: Request code review and finish the branch**

Use `superpowers:requesting-code-review`, address verified findings, rerun affected tests, and then use `superpowers:finishing-a-development-branch` to prepare the PR/integration choice. Report that no real KIS request, order, cancellation, correction, balance, or account call was made during development verification.
