# Operations Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the misleading seeded trade dashboard with a responsive, local execution-story cockpit for one pipeline run.

**Architecture:** `db.py` remains the only schema owner and assembles a secret-free run snapshot. `dashboard.py` serves one build-free HTML shell and a run-scoped JSON API. Vanilla JS polls data without full-page reloads and renders truth bar, timeline, deliveries, orders, portfolio, analyses, and lessons.

**Tech Stack:** FastAPI, SQLite, HTML/CSS/vanilla JS, `unittest`, browser screenshots, visual-verdict

## Global Constraints

- Follow root `DESIGN.md`.
- Bind to `127.0.0.1` by default.
- Never seed realistic trades into an empty DB.
- Never infer holdings from the latest 20 BUY rows.
- Escape all stored text and return no secret/account fields.
- No frontend build step or remote font dependency.

---

### Task 1: Run-scoped dashboard snapshot

**Files:**
- Modify: `db.py`
- Create: `tests/test_dashboard_data.py`

**Interfaces:**
- Produces: `get_dashboard_snapshot(run_id: str = "latest") -> dict`
- Consumes: run/event/delivery/order/portfolio tables from earlier plans

- [ ] **Step 1: Write failing empty, mock, failed, partial-fill, and redaction fixtures**

```python
def test_blocked_order_never_becomes_a_position(self):
    snapshot = db.get_dashboard_snapshot("run-1")
    self.assertEqual([], snapshot["positions"])
    self.assertEqual("blocked", snapshot["orders"][0]["status"])
```

- [ ] **Step 2: Run and confirm snapshot API is missing**

- [ ] **Step 3: Implement one-run assembly**

Return `run`, ordered `events`, `deliveries`, `orders`, `portfolio`, `positions`, `analyses`, and `lessons`. Use explicit allowlists and decoded safe JSON; do not return raw broker payloads.

- [ ] **Step 4: Run data tests**

Expected: empty state, source/date preservation, accepted-vs-filled, partial position, channel status, and redaction PASS.

- [ ] **Step 5: Commit snapshot query with a Lore message**

### Task 2: API and secure HTML shell

**Files:**
- Rewrite: `dashboard.py`
- Create: `tests/test_dashboard_api.py`

**Interfaces:**
- Produces: `GET /api/dashboard?run_id=latest`, compatible `GET /api/data`, `GET /`

- [ ] **Step 1: Write failing API, binding, escaping, and no-seed tests**

```python
def test_dashboard_does_not_seed_or_render_script_payload(self):
    db.save_lesson("005930", "PASS", "<script>alert(1)</script>")
    html = dashboard.index().body.decode()
    self.assertNotIn("<script>alert(1)</script>", html)
```

- [ ] **Step 2: Run and confirm current duplicate schema/seed and escaping failures**

- [ ] **Step 3: Replace dashboard DB ownership and shell**

Call `db.init_db()` in lifespan, use `db.get_dashboard_snapshot`, bind localhost, remove `_seed_demo_data`, remove Google Fonts, and keep `/api/data` as a compatibility projection.

- [ ] **Step 4: Run API and HTML tests**

Expected: PASS; starting dashboard in an empty temp directory adds no trade rows.

- [ ] **Step 5: Commit dashboard backend contract with a Lore message**

### Task 3: Execution-story UI

**Files:**
- Modify: `dashboard.py`
- Modify: `tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `/api/dashboard` payload and root `DESIGN.md`
- Produces: responsive truth bar, timeline, delivery/order/portfolio/analysis/lesson components

- [ ] **Step 1: Add structural tests for required regions and accessible status labels**

```python
for marker in ("truth-bar", "pipeline-timeline", "delivery-health", "order-truth", "portfolio", "analysis-decisions", "learning-log"):
    self.assertIn(f'id="{marker}"', html)
```

- [ ] **Step 2: Run and confirm markers are absent**

- [ ] **Step 3: Implement responsive vanilla-JS rendering**

Poll `/api/dashboard` every 10 seconds, preserve the last confirmed run on fetch failure, show data date separately from refresh time, use text plus color for states, contain wide tables, and provide empty/error states with coding-agent prompts.

- [ ] **Step 4: Run dashboard unit tests**

Expected: PASS for Korean long text, null fields, state vocabulary, no remote assets, and mobile structure.

- [ ] **Step 5: Commit UI implementation with a Lore message**

### Task 4: Visual verdict loop

**Files:**
- Create locally only: visual screenshots under `.omx/artifacts/visual-ralph/` or `/private/tmp`
- Modify only if verdict requires: `dashboard.py`, `DESIGN.md`

**Interfaces:**
- Produces: reproducible verdict evidence for desktop and mobile fixtures

- [ ] **Step 1: Start the dashboard against deterministic fixture DB data**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache .venv/bin/python dashboard.py`

Expected: `http://127.0.0.1:8080` responds.

- [ ] **Step 2: Capture 1440×900, 1280×720, and 390×844 for empty, mock, market-closed, channel-failure, partial-fill, and failed-stage states**

- [ ] **Step 3: Run `visual-verdict` after each screenshot set**

Expected: no overflow, clipped labels, false live claims, color-only status, or illegible contrast.

- [ ] **Step 4: Apply the smallest visual corrections and repeat verdict until pass**

- [ ] **Step 5: Run dashboard tests once more and commit any corrections**
