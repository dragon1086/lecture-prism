# Observable Paper-Trading System Design

## Status

- Approved direction: 2026-07-15
- Product owner instruction: implement autonomously with thorough verification
- Scope: pipeline observability, Discord and Telegram delivery, market-day handling, KIS paper trading, dashboard, curriculum, and Strategy Harness

## Outcome

`lecture-prism` must remain an API-key-free teaching demo while becoming a trustworthy personal paper-trading system when optional integrations are configured.

A learner must be able to prove, from one run, which data was used, how each stage completed, what the system decided, whether an order was merely blocked or accepted or actually filled, whether Discord and Telegram received the event, and what was saved for later review.

## Non-negotiable constraints

1. `python3 main.py` completes with the standard library and no `.env`.
2. Missing or broken notifications never stop screening, analysis, trading decisions, feedback, or DB persistence.
3. Broker orders fail closed when market status, credentials, time window, or safety gates are uncertain.
4. An accepted order is never described as filled.
5. Weekend and holiday runs analyze the latest available trading-day data but do not submit orders.
6. Existing strategy function signatures remain compatible.
7. Discord and Telegram are optional runtime integrations; Discord is a required Week 3 preparation artifact, Telegram is optional.
8. Secrets, account numbers, webhook URLs, bot tokens, and raw broker responses are not logged, persisted in public-facing tables, or returned by dashboard APIs.
9. No new mandatory dependency is introduced for the demo path.
10. The dashboard binds to localhost by default and never fabricates realistic holdings in an empty production DB.

## Delivery decomposition

The work is implemented in four ordered slices because later slices consume contracts created by earlier ones.

1. **Observable pipeline:** event model, notification dispatcher, data provenance, DB run/event records.
2. **KIS paper execution:** clean-room KIS client, market calendar, balances, orders, reconciliation, persistence.
3. **Operations dashboard:** run story, delivery health, order truth, portfolio snapshots, analysis and lessons.
4. **Teaching and harness:** Week 3/4 assignments, prompts, System Completion Lane, contract tests.

## Runtime architecture

```text
run_pipeline()
  ├─ PipelineRecorder ───────────────> SQLite
  ├─ NotificationDispatcher.enqueue(event)
  │    └─ single FIFO worker
  │         ├─ DiscordWebhookChannel ─┐
  │         └─ TelegramBotChannel ────┴─ concurrent fan-out per event
  ├─ screening -> analysis -> trading -> feedback
  ├─ MarketContext
  │    ├─ latest data_as_of
  │    └─ market open/order permission
  └─ BrokerAdapter
       └─ KISClient (paper by default, real fail-closed)
```

`run_pipeline()` stays async. It starts one FIFO notification worker, enqueues events without waiting for HTTP delivery, and closes the dispatcher in `finally`. The worker completes all configured channel deliveries for event N before processing event N+1. Discord and Telegram deliveries for the same event run concurrently with `asyncio.gather(..., return_exceptions=True)`.

## Pipeline event contract

Every event contains:

| Field | Meaning |
|---|---|
| `run_id` | UUID for one pipeline run |
| `sequence` | Monotonic integer starting at 1 |
| `event_type` | Stable machine-readable type |
| `status` | `started`, `succeeded`, `skipped`, or `failed` |
| `occurred_at` | UTC ISO-8601 timestamp |
| `profile` | `mock`, `real_data`, `research`, `paper`, or `live` |
| `trade_state` | `simulation`, `paper`, `live_blocked`, or `real` |
| `data_source` | `mock`, `yfinance`, `kis`, or mixed summary |
| `data_as_of` | Latest actual market-data business date, if known |
| `ticker` | Optional ticker for per-stock events |
| `summary` | Short learner-facing Korean sentence |
| `details` | Secret-free structured payload |

Minimum ordered lifecycle:

1. `pipeline.started`
2. `market.checked`
3. `screening.started`
4. `screening.completed`
5. `analysis.started` and `analysis.completed` per ticker
6. `trading.started`
7. `trading.decision` per ticker
8. `order.status` for every broker decision or skip
9. `feedback.saved`
10. `pipeline.completed` or `pipeline.failed`

The event key `(run_id, sequence, channel)` is unique for notification delivery records. Redelivery is at-least-once within bounded retries, with duplicates suppressed after confirmed success.

## Notification delivery

### Configuration

```dotenv
LECTURE_NOTIFY_DISCORD=0
DISCORD_WEBHOOK_URL=

LECTURE_NOTIFY_TELEGRAM=0
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Missing settings create no-op channels and a safe configuration warning. They never raise during pipeline startup.

### Transport

- Use standard-library JSON and HTTP transport, wrapped with `asyncio.to_thread()`.
- Discord uses an Incoming Webhook and `wait=true` confirmation.
- Telegram uses the Bot API `sendMessage` endpoint.
- Discord messages are split below 2,000 characters.
- Telegram messages are split below 4,096 characters.
- Splitter prefers line boundaries and hard-splits overlong single lines.
- Mentions are disabled on Discord; Telegram defaults to plain text.
- HTTP timeouts and retry counts are bounded.
- Retry 429 using a capped `retry_after`; retry timeouts and 5xx with bounded exponential backoff.
- Never automatically retry an order POST; notification retries are safe.
- Dispatcher close uses a flush deadline and cancels remaining delivery work after logging a redacted warning.

Patterns are adapted from PRISM's task tracking, final drain, RetryAfter handling, timeout backoff, and plain-text fallback. PRISM's Firebase, PDF, translation, directory queue, and long-running conversational bot code are excluded.

## Market date and order permission

Analysis permission and order permission are independent.

```text
analysis_allowed = latest market data exists

order_allowed =
    KIS opnd_yn == "Y"
    AND current KST order window permits the requested order type
    AND broker credentials are valid
    AND broker enable flag is set
    AND real-money double gate is set when mode == real
```

- `data_as_of` is the latest returned business date, not an assumed Friday.
- Weekend runs use latest available data and produce `decision_only` / `market_closed` order status.
- KIS holiday results are cached once per KST date.
- If holiday API and cache both fail, analysis continues and orders are blocked.
- Public-holiday libraries may provide a hint but do not replace KIS `opnd_yn`.

## KIS paper client

The teaching runtime clean-room implements the official API contract instead of importing PRISM's YAML-heavy trading module.

### Capabilities

- paper authentication and token cache separated from real mode
- current/daily prices and latest `stck_bsop_date`
- balance and holdings with pagination
- orderable quantity
- cash BUY and SELL
- order acceptance persistence
- daily fill inquiry and reconciliation
- partial fill, full fill, unfilled, rejected, cancelled, and unknown states
- cancel remaining quantity only after a cancellable-quantity check
- holiday/open-day lookup and daily cache

### Order state contract

```text
submitting
  ├─ accepted -> unfilled -> partial_fill -> filled
  │                          └─ cancel_requested -> cancelled
  ├─ rejected
  ├─ unknown       # ambiguous network outcome; reconcile, never blind-retry
  └─ blocked       # safety, market, balance, or configuration gate
```

`executed=True` only when status is `filled`. `accepted`, `unfilled`, and `partial_fill` remain distinct. POST timeout becomes `unknown`, is persisted, and is reconciled through inquiry rather than automatically resubmitted.

### Broker safety

- Paper and real credentials/tokens are namespaced.
- BUY is capped by KIS orderable quantity.
- SELL is capped by actual holding quantity.
- Real mode retains `LECTURE_ENABLE_LIVE_BROKER` plus `LECTURE_ALLOW_REAL_BROKER`.
- Paper mode may reach the external paper server only when its explicit broker enable flag is set.
- Cancellation support is considered credentialed-smoke-test pending until the official paper TR behavior is verified.

## Persistence model

`db.py` is the only schema and migration owner. `dashboard.py` must not define tables or seed realistic trades.

New tables:

- `pipeline_runs`: run identity, profile, trade state, source, data date, market status, start/end, final status, failure stage.
- `pipeline_events`: ordered event history and redacted payload.
- `notification_deliveries`: channel, event sequence, queued/sent/failed/skipped status, attempts, timestamps, redacted error.
- `broker_orders`: client/order identity, broker, mode, ticker, side, requested/filled/remaining quantity, prices, status, timestamps.
- `market_calendar_cache`: date, open flag, source, fetched timestamp.
- `portfolio_snapshots`: run-level cash, total evaluation, realized/unrealized P&L, source.
- `position_snapshots`: ticker-level quantity, average/current price, value, P&L.

Existing analysis, trade, and lesson records gain nullable `run_id`; analysis also keeps profile, source, and data date. Migrations are additive and idempotent.

## Operations dashboard

The dashboard becomes an execution-story cockpit, not a decorative performance report.

### Information hierarchy

1. **Truth bar:** latest run status, data-as-of, market open/closed, profile, data source, execution mode, page refresh time.
2. **Pipeline timeline:** ordered stage cards with completed, skipped, failed, and in-progress states.
3. **Delivery health:** Discord and Telegram configured/sent/failed/skipped, without secret values.
4. **Order truth:** decision, blocked/accepted/partial/filled/rejected status, requested and filled quantities, safe broker order reference.
5. **Portfolio snapshot:** source, cash, holdings, evaluation, realized/unrealized P&L; never inferred from the latest 20 BUY rows.
6. **Analysis decisions:** recommendation, score, data date, rationale, risks, six-section detail.
7. **Learning log:** feedback lessons connected to the run.

### UX rules

- Use the existing build-free FastAPI + single-HTML approach.
- Serve a shell and fetch `/api/dashboard?run_id=latest` for updates instead of full-page reloads.
- Keep API output secret-free and run-scoped.
- Empty state says no run exists; it does not insert fake trades.
- Distinguish page refresh time, event time, and market data date.
- Distinguish decision, order acceptance, and fill in both text and color.
- Bind to `127.0.0.1` by default.
- Escape all analysis, news, error, and lesson text.
- Remove external font dependency so local/offline display remains complete.
- Support 1440×900, 1280×720, and 390×844 without page-level horizontal scrolling.
- Use text/icon labels in addition to color.

## Curriculum and Strategy Harness

### Week 3 required preparation

- Create a personal Discord server/channel and Incoming Webhook.
- Store the webhook only in ignored `.env`.
- Receive one harmless test message.
- Prepare KIS paper App Key/Secret and paper account identifier locally.
- Verify no secret is staged or submitted.

Optional extension:

- Create a Telegram bot, initiate the conversation, discover Chat ID, store token/ID in `.env`, and receive a test message.

Student documents use coding-agent prompts rather than direct terminal command blocks.

### Week 4 completion evidence

- One Strategy Lane A/B/C/D modification passes before system integration.
- One run shows the same `run_id` and increasing sequence on Discord.
- Telegram shows the same events when configured.
- The last available market-data date is explicit.
- Decision/order/fill status is explicit.
- Dashboard shows the same run and channel/order states.
- Secrets are absent from Git and screenshots.

### Harness

Keep A/B/C/D as the only strategy-editing tracks. Add a separate `System Completion Lane` that:

1. validates the keyless demo,
2. checks Discord required readiness and optional Telegram readiness,
3. checks source/date provenance,
4. references a pinned official KIS checkout when KIS work is requested,
5. verifies paper-only account/order behavior,
6. verifies dashboard evidence,
7. verifies secret hygiene and live blocking.

The three skill copies remain byte-identical. The harness never creates notification implementations repeatedly inside a strategy track.

## Verification strategy

### Unit and contract tests

- event ordering, run ID, sequence, dispatcher drain, split boundaries, redaction, retry and timeout behavior
- market cache, weekend/holiday behavior, latest data date
- KIS auth namespace, request fields/TR IDs, pagination, balance, BUY/SELL, no blind POST retry
- order transitions including accepted/unfilled/partial/filled/rejected/cancelled/unknown/blocked
- DB additive migration, idempotent upsert, restart reconciliation
- dashboard API empty, stale-data, failed-stage, notification failure, partial-fill and secret-redaction fixtures
- HTML escaping and responsive structural contracts
- curriculum/harness copy parity and required wording

### Integration tests

- keyless mock full pipeline
- Discord-only, Telegram-only, and dual-channel fake transports
- one channel fails while the other and the pipeline complete
- weekend latest-data decision with no order
- paper order accepted then reconciled to fill fixture
- real mode remains double-gated
- dashboard reads the exact latest run and never fabricates holdings

### Optional credentialed smoke tests

- Discord test webhook
- Telegram test chat
- KIS paper balance and quote
- KIS paper BUY/SELL only during an explicit test window with tiny quantity
- fill inquiry and cancellation behavior

These tests are opt-in, never run in CI, never print secrets, and must not be required for the API-key-free demo.

### Visual QA

Capture and judge at 1440×900, 1280×720, and 390×844 for:

- empty state
- successful mock run
- market-closed decision-only run
- Discord failure with Telegram success
- KIS accepted/unfilled and partial/fill states
- failed pipeline stage
- stale/latest-market-data warning

Every visual iteration receives a visual verdict before the next edit.

## Acceptance criteria

The work is complete only when:

1. baseline and expanded automated tests pass;
2. keyless `python3 main.py` completes;
3. notification failure cannot change pipeline results;
4. weekend analysis continues and orders are blocked;
5. order acceptance and fill are distinct in DB, messages, and dashboard;
6. dashboard uses `db.py` as the schema source and binds locally;
7. Week 3/4 docs and harness reflect Discord required / Telegram optional;
8. live trading remains fail-closed;
9. secret and local-path scans are clean;
10. dashboard visual verdicts pass at desktop and mobile sizes.

## Explicit non-goals

- profitability guarantees or performance claims
- real-money execution during class
- a conversational Discord/Telegram bot
- WebSocket fill notifications in the first version
- replacing the build-free dashboard with a frontend framework
- copying unlicensed upstream source wholesale
