# Observable Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one truthful pipeline run and asynchronously fan each ordered event to configured Discord and Telegram channels without breaking the keyless demo.

**Architecture:** `PipelineEvent` is the shared contract. `NotificationDispatcher` owns one FIFO queue and concurrently fans each event to channel adapters. `db.py` persists runs, events, and redacted delivery status; `main.py` emits events and always drains the dispatcher.

**Tech Stack:** Python 3.10+, `asyncio`, `dataclasses`, `urllib`, SQLite, `unittest`

## Global Constraints

- `python3 main.py` must complete with no `.env` and no new mandatory dependency.
- Notification failures are fail-open and never alter pipeline results.
- Event order is stable and secrets are never logged or persisted.
- Existing `run_screening`, `run_analysis`, `run_trading`, and `run_feedback` signatures remain compatible.

---

### Task 1: Event and delivery persistence

**Files:**
- Modify: `db.py`
- Test: `tests/test_pipeline_store.py`

**Interfaces:**
- Produces: `start_pipeline_run(run: dict)`, `finish_pipeline_run(run_id: str, status: str, failure_stage: str | None = None)`, `save_pipeline_event(event: dict)`, `save_notification_delivery(delivery: dict)`, `get_latest_pipeline_run()`

- [ ] **Step 1: Write failing migration and ordering tests**

```python
def test_pipeline_events_are_ordered_and_delivery_is_redacted(self):
    db.start_pipeline_run({"run_id": "run-1", "profile": "mock", "trade_state": "simulation"})
    db.save_pipeline_event({"run_id": "run-1", "sequence": 2, "event_type": "screening.completed"})
    db.save_pipeline_event({"run_id": "run-1", "sequence": 1, "event_type": "pipeline.started"})
    rows = db.get_pipeline_events("run-1")
    self.assertEqual([1, 2], [row["sequence"] for row in rows])
```

- [ ] **Step 2: Run the focused test and confirm missing-table/API failure**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_pipeline_store -v`

Expected: FAIL because pipeline persistence APIs do not exist.

- [ ] **Step 3: Add additive idempotent schema and APIs**

```python
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    trade_state TEXT NOT NULL,
    data_source TEXT,
    data_as_of TEXT,
    market_status TEXT,
    failure_stage TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    ticker TEXT,
    summary TEXT,
    details TEXT,
    UNIQUE(run_id, sequence)
);
```

Store only sanitized error text in `notification_deliveries`; never accept webhook/token fields.

- [ ] **Step 4: Run migration twice and focused tests**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_pipeline_store -v`

Expected: PASS, including two consecutive `init_db()` calls.

- [ ] **Step 5: Commit only DB and test files with a Lore message**

### Task 2: FIFO notification dispatcher

**Files:**
- Create: `notifications.py`
- Create: `tests/test_notifications.py`

**Interfaces:**
- Produces: `PipelineEvent`, `NotificationChannel.send(event)`, `NotificationDispatcher.start()`, `enqueue(event)`, `close(timeout=...)`, `build_notification_dispatcher()`
- Consumes: persistence functions from Task 1

- [ ] **Step 1: Write failing FIFO, fan-out, failure-isolation, split, retry, and redaction tests**

```python
async def test_dispatcher_preserves_event_order_and_fans_out_concurrently(self):
    discord, telegram = FakeChannel(), FakeChannel()
    dispatcher = NotificationDispatcher([discord, telegram])
    await dispatcher.start()
    await dispatcher.enqueue(PipelineEvent(run_id="r", sequence=1, event_type="pipeline.started"))
    await dispatcher.enqueue(PipelineEvent(run_id="r", sequence=2, event_type="pipeline.completed"))
    await dispatcher.close()
    self.assertEqual([1, 2], discord.sequences)
    self.assertEqual([1, 2], telegram.sequences)
```

- [ ] **Step 2: Run and confirm import failure**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_notifications -v`

Expected: FAIL because `notifications.py` does not exist.

- [ ] **Step 3: Implement the minimal contract and worker**

```python
@dataclass(frozen=True)
class PipelineEvent:
    run_id: str
    sequence: int
    event_type: str
    status: str = "succeeded"
    occurred_at: str = field(default_factory=_utc_now)
    profile: str = "mock"
    trade_state: str = "simulation"
    data_source: str | None = None
    data_as_of: str | None = None
    ticker: str | None = None
    summary: str = ""
    details: dict[str, object] = field(default_factory=dict)

async def _deliver(self, event):
    await asyncio.gather(*(channel.send(event) for channel in self.channels), return_exceptions=True)
```

Use `asyncio.to_thread()` around `urllib.request.urlopen`. Cap retries, `retry_after`, and close time. Disable Discord mentions and default Telegram to plain text.

- [ ] **Step 4: Run notification tests**

Expected: FIFO, concurrency, disabled-channel, one-channel-fails, 429, timeout, 2,000/4,096 split, flush timeout, and secret-redaction tests PASS.

- [ ] **Step 5: Commit notification files with a Lore message**

### Task 3: Market-data provenance

**Files:**
- Modify: `data_source.py`
- Modify: `analysis.py`
- Create: `tests/test_market_data_as_of.py`

**Interfaces:**
- Produces: stock-data fields `data_source`, `data_as_of`; analysis output preserves both

- [ ] **Step 1: Write failing weekend/latest-date and mock-provenance tests**

```python
def test_yfinance_result_uses_latest_history_date_not_today(self):
    result = data_source._profile_from_history(fake_history(last_date="2026-07-10"))
    self.assertEqual("2026-07-10", result["data_as_of"])
```

- [ ] **Step 2: Run and confirm `data_as_of` is missing**

- [ ] **Step 3: Add provenance without changing existing return compatibility**

Mock results set a clearly labelled synthetic data date or `None`; real results derive the final history index date. `run_analysis()` copies it to its result.

- [ ] **Step 4: Run data-source, analysis, and provenance tests**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_data_source_modes tests.test_analysis_runtime_config tests.test_market_data_as_of -v`

Expected: PASS.

- [ ] **Step 5: Commit provenance changes with a Lore message**

### Task 4: Orchestrator integration

**Files:**
- Modify: `main.py`
- Modify: `runtime_config.py`
- Modify: `.env.example`
- Create: `tests/test_main_notifications.py`
- Modify: `tests/test_runtime_config.py`

**Interfaces:**
- Consumes: `PipelineEvent`, dispatcher builder, DB run/event APIs
- Produces: stable ordered lifecycle and final flush on every exit path

- [ ] **Step 1: Write failing normal, empty-candidate, stage-failure, and notification-failure tests**

```python
async def test_empty_screening_still_completes_and_flushes(self):
    await main.run_pipeline(dispatcher=self.dispatcher)
    self.assertEqual("pipeline.completed", self.dispatcher.events[-1].event_type)
    self.assertTrue(self.dispatcher.closed)
```

- [ ] **Step 2: Run and confirm `run_pipeline` lacks dispatcher lifecycle**

- [ ] **Step 3: Add optional injection and lifecycle**

```python
async def run_pipeline(..., dispatcher=None):
    dispatcher = dispatcher or build_notification_dispatcher()
    await dispatcher.start()
    try:
        ...
    except Exception:
        await emit("pipeline.failed", status="failed")
        raise
    finally:
        await dispatcher.close(timeout=5.0)
```

Preserve CLI behavior and OAuth cleanup. Redact notification settings from `RuntimeConfig.summary()`.

- [ ] **Step 4: Run all observable-pipeline tests and keyless demo**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_pipeline_store tests.test_notifications tests.test_market_data_as_of tests.test_main_notifications tests.test_runtime_config -v`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache LECTURE_SAVE_REPORTS=0 python3 main.py`

Expected: tests PASS; demo completes and notification settings may be absent.

- [ ] **Step 5: Commit orchestrator integration with a Lore message**
