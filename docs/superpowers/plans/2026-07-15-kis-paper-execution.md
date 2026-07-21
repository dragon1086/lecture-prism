# KIS Paper Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clean-room, mock-first KIS paper client that distinguishes order acceptance from fill and safely supports balance, BUY, SELL, inquiry, reconciliation, holiday gating, and cancellation.

**Architecture:** `KISClient` owns official HTTP contracts with injected transport and clock. `KISBrokerAdapter` maps domain orders to the client. `db.py` persists monotonic order state and the market calendar; `trading.py` uses actual paper balance when configured and never blind-retries an ambiguous order POST.

**Tech Stack:** Python 3.10+, standard-library HTTP/JSON, SQLite, `unittest`, official KIS REST contracts

## Global Constraints

- Importing `main`, `trading`, or `brokers` without KIS configuration performs no network or optional-package import.
- Paper and real credentials/tokens are isolated.
- Real orders retain the existing double safety gate.
- POST timeout is `unknown`, not an automatic retry.
- `executed=True` only for `filled`.

---

### Task 1: KIS client request contracts

**Files:**
- Create: `brokers/kis_client.py`
- Create: `tests/test_kis_client.py`

**Interfaces:**
- Produces: `KISConfig.from_env()`, `KISClient.authenticate()`, `get_balance()`, `get_orderable_quantity()`, `place_cash_order()`, `get_order_status()`, `get_market_day()`, `get_daily_prices()`, `cancel_order()`

- [ ] **Step 1: Write failing request-shape tests with an injected fake transport**

```python
def test_paper_buy_and_sell_use_distinct_tr_ids(self):
    client.place_cash_order("005930", "BUY", 1, 70000)
    self.assertEqual("VTTC0012U", self.transport.last_headers["tr_id"])
    client.place_cash_order("005930", "SELL", 1, 70000)
    self.assertEqual("VTTC0011U", self.transport.last_headers["tr_id"])
```

Cover token namespace, balance pagination, orderable quantity, strings for quantity/price, fill inquiry, daily business date, holiday `opnd_yn`, no POST retry, redaction, and cancellation payload.

- [ ] **Step 2: Run and confirm module import failure**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_kis_client -v`

- [ ] **Step 3: Implement minimal client with transport and clock injection**

```python
@dataclass(frozen=True)
class KISConfig:
    mode: str
    app_key: str
    app_secret: str
    account_no: str
    product_code: str = "01"

class KISClient:
    def __init__(self, config, transport=None, clock=None): ...
```

Do not import upstream `kis_auth.py`; copy no substantial upstream implementation. Validate response fields and return structured errors.

- [ ] **Step 4: Run client tests and import smoke test**

Run: `python3 -c "import main, trading, brokers.kis_client"`

Expected: no network and no optional KIS dependency import.

- [ ] **Step 5: Commit client and tests with a Lore message**

### Task 2: Order and market persistence

**Files:**
- Modify: `db.py`
- Create: `tests/test_kis_order_store.py`

**Interfaces:**
- Produces: `save_broker_order()`, `update_broker_order()`, `get_pending_broker_orders()`, `save_market_day()`, `get_market_day()`

- [ ] **Step 1: Write failing idempotency and state-monotonicity tests**

```python
def test_order_state_cannot_regress_from_filled_to_accepted(self):
    db.save_broker_order(order(status="filled"))
    with self.assertRaises(ValueError):
        db.update_broker_order(order(status="accepted"))
```

- [ ] **Step 2: Run and confirm missing APIs**

- [ ] **Step 3: Add `broker_orders` and `market_calendar_cache`**

Use unique `(broker, mode, order_date, org_no, order_no)` when broker identifiers exist; use a client request ID before acceptance. Persist requested, filled, remaining quantity and average fill price. Add indexes for pending-state recovery.

- [ ] **Step 4: Run persistence tests twice against the same migrated DB**

Expected: additive migration, duplicate acceptance upsert, accepted→partial→filled, and pending recovery PASS.

- [ ] **Step 5: Commit store changes with a Lore message**

### Task 3: Broker adapter and market gate

**Files:**
- Modify: `brokers/kis.py`
- Create: `market_calendar.py`
- Modify: `tests/test_broker_adapters.py`
- Create: `tests/test_market_calendar.py`

**Interfaces:**
- Produces: adapter `place_order`, `get_account`, `get_order_status`, `cancel_order`, `is_market_open`; `MarketGate.check(now) -> MarketStatus`
- Consumes: client and DB cache from Tasks 1–2

- [ ] **Step 1: Write failing BUY/SELL, weekend, API-failure, and existing live-gate tests**

```python
def test_weekend_blocks_order_but_not_analysis(self):
    status = self.gate.check(datetime(2026, 7, 18, 10, tzinfo=KST))
    self.assertFalse(status.order_allowed)
    self.assertEqual("market_closed", status.reason)
```

- [ ] **Step 2: Run and confirm legacy adapter is BUY-only**

- [ ] **Step 3: Replace dynamic legacy import with `KISClient` composition**

Keep `brokers/base.py` compatible. Check weekend, cached `opnd_yn`, and KST window before POST. API/cache uncertainty blocks only orders.

- [ ] **Step 4: Run adapter/calendar regression tests**

Expected: KIS BUY/SELL pass; Kiwoom/Toss and double-gate tests remain green.

- [ ] **Step 5: Commit adapter and calendar with a Lore message**

### Task 4: Trading, reconciliation, and feedback truth

**Files:**
- Modify: `trading.py`
- Modify: `feedback.py`
- Create: `tests/test_kis_trading_flow.py`

**Interfaces:**
- Consumes: adapter account/order APIs and DB order store
- Produces: trade results containing `status`, `accepted`, `executed`, `terminal`, `requested_qty`, `filled_qty`, `remaining_qty`, `order_no`, `message`

- [ ] **Step 1: Write failing tests for orderable BUY, holding-capped SELL, acceptance, partial fill, unknown, and feedback**

```python
def test_accepted_order_is_not_executed(self):
    result = await trading.run_trading([analysis()], dry_run=False)
    self.assertEqual("accepted", result[0]["status"])
    self.assertFalse(result[0]["executed"])
```

- [ ] **Step 2: Run and confirm current `success -> executed` defect**

- [ ] **Step 3: Implement state mapping and reconciliation**

Fix SELL quantity propagation, calculate paper sizes from account data, persist acceptance before inquiry, update through monotonic states, and make feedback treat only fills as completed trades. Preserve simulation behavior.

- [ ] **Step 4: Run KIS flow plus full broker tests**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 -m unittest tests.test_kis_client tests.test_kis_order_store tests.test_market_calendar tests.test_broker_adapters tests.test_kis_trading_flow -v`

Expected: PASS.

- [ ] **Step 5: Run keyless demo and live-blocked CLI regression**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache LECTURE_SAVE_REPORTS=0 python3 main.py`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/lecture-prism-pycache python3 trading.py --live`

Expected: demo completes; live returns `live_blocked` without an external order.

- [ ] **Step 6: Commit trading integration with a Lore message**
