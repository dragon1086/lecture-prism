# Current Architecture Documentation Refresh Design

> Status: approved for implementation
>
> Approved: 2026-07-22
>
> Scope: learner-facing documentation and its maintained architecture visuals

## Decision

Refresh the learner-facing documentation around two explicitly different
runtime paths instead of presenting the original four-file demo as the whole
system.

1. **Foundation path** — `mock` and `real_data` use the root teaching
   pipeline.  It is the keyless first-success route and the place where a
   learner normally changes one of the A/B/C/D strategy tracks.
2. **Stateful operating path** — `classroom`, `backtest`, `paper`, and `live`
   introduce `prism_core`, deterministic replay, market regime, a persistent
   ledger, and broker order reconciliation.  These profiles do not turn a
   failed market-data provider into a mock trade.

The public teaching story remains “a learner states a strategy and a coding
agent implements one safe change.”  The refresh makes the safety boundary
visible: deterministic rules own the score, price, position, and order gates;
the optional official Codex OAuth call supplies qualitative interpretation and
may only veto a BUY.  KIS and the optional Toss WTS adapter both support
BUY/SELL, status lookup, partial/full-fill reconciliation, cancellation, and
restart reconciliation.  That implementation coverage must never be described
as an actual-account end-to-end test.

## Evidence Being Preserved

- `python3 main.py` remains a standard-library, no-key first-success path.
- `classroom` is fixed offline replay with a stateful local `PaperBroker`;
  `backtest` retains a legacy stateless simulation route.
- `paper` and `live` require real market data and block instead of silently
  falling back when their provider fails.
- The full broker lifecycle is implemented and fixture-tested for KIS and
  Toss; live-account E2E is deliberately not performed by automated tests.
- Core-table dashboard screens are not implemented.  The current dashboard
  shows legacy `trade_history`, `analysis_decisions`, and `feedback_lessons`.

## Information Architecture

### Reader journey

`README.md` gives an outcome-first overview, keeps the first run intentionally
simple, and links to the correct next page for each path.  `START_HERE.md`
finishes the keyless run, then offers a clearly named fork:

- Strategy track A/B/C/D in the root teaching pipeline
- Classroom replay to inspect persisted regime/candidate/order/fill evidence
- Optional OAuth, real-data, and broker integrations

`docs/architecture.md` becomes the reference map.  It opens with the two-path
model, then explains the shared safety contracts, not the historical root
pipeline alone.  `docs/runtime-profiles.md` is the operational source of truth
for each profile.  It owns the exact distinction among mock fallback,
fail-closed data providers, and the separate live-order gate.

### Teaching language

- Say “one structured qualitative analysis call” rather than a strategy LLM
  agent or a sequential three-agent chain.
- Say “rule-owned quantitative decision; LLM can veto BUY to HOLD” rather than
  suggesting the model sets the recommendation, score, target, or stop.
- Say “full lifecycle implementation and fixture verification” rather than
  “live lifecycle verified.”
- Say “root demo universe” rather than “about 2,700 stocks.”  Detailed
  `prism_core` screening is a separate stateful path.
- Identify `docs/prism-insight/` as original-system reference material, not as
  a description of the currently executed lecture runtime.

## Visual System

Five maintained README/architecture visuals will be replaced with new
information-dense raster infographics generated with GPT Image 2:

| Asset | Job | Required accurate content |
|---|---|---|
| `strategy-to-kis.png` | Course journey | First success → one-track strategy change → two runtime paths → optional broker lifecycle |
| `system-result.png` | Runtime result | Rules/LLM boundary, entry/exit order lifecycle, evidence ledger, unknown-state stop |
| `runtime-architecture-map.png` | Profile map | All seven profiles, local/offline versus real-data boundary, KIS and Toss, fail-closed/live gate |
| `module-guide.png` | Ownership map | Root teaching modules versus `prism_core`; technical/news qualitative interpretation and rule-owned output |
| `optional-integrations-safety.png` | Connection/safety map | Optional Codex OAuth, market data, KIS/Toss, no automatic real order, dual live gate |

The generated artwork must use a clean Korean educational-infographic style:
high contrast, clear grid, no product logos, no fabricated API UI, no claims
about returns or live-account validation.  Exact technical prose remains in
Markdown; labels in the images are intentionally short so visual text stays
legible.  Existing historical `docs/assets/prism-insight/` images are retained
and their parent documentation is labelled as reference material.

## Documentation Changes

| Area | Change |
|---|---|
| README and START_HERE | Update the high-level outcome and navigation without making the first run more complex. |
| Part 3 and Part 4 exercises | Remove “future task” OAuth language; distinguish root Track A from `prism_core` detailed screening; correct LLM ownership. |
| Architecture/runtime/defaults/multi-agent docs | Make the current two-path structure and broker/LLM contracts authoritative and internally consistent. |
| API-key and broker docs | Keep installation/setup prompts agent-oriented, clarify Codex OAuth and the implemented KIS/Toss lifecycle. |
| Tests | Extend document-contract assertions to pin the current safety claims and rule/LLM ownership. |

## Boundaries and Non-goals

- Do not change runtime, broker, database, or strategy behavior.
- Do not add a dependency.  The documentation image assets are checked-in
  files, not a runtime requirement.
- Do not regenerate `docs/assets/prism-insight/`; they remain historical
  reference assets.
- Do not claim a Toss or KIS real-account E2E execution.
- Do not rewrite the pre-opening seminar slide deck in this change; it is a
  dated presentation artifact, not one of the linked learner documentation
  surfaces.  Its later refresh can reuse this terminology.

## Verification

1. Run focused document-contract tests and update their assertions for the
   exact current contracts above.
2. Run the whole unit suite plus the keyless `python3 main.py` smoke run to
   prove documentation-only work did not disturb the default teaching path.
3. Check every edited Markdown link and image reference exists.
4. Inspect each generated image at full size and after README-scale rendering
   for readable labels, correct safety terminology, and no secret-like text.
5. Search the learner-facing surfaces for the retired claims: “후속 과제” for
   OAuth, a strategy prompt/agent, a 2,700-stock root demo, and KIS buy-only
   wording.
