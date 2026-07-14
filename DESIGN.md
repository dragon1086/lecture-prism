# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-07-15
- Primary product surfaces: local operations dashboard, Discord reports, Telegram reports, student exercise guides
- Evidence reviewed: `dashboard.py`, `db.py`, `main.py`, `analysis.py`, `trading.py`, `feedback.py`, `README.md`, `docs/architecture.md`, PRISM orchestration/Telegram patterns, and KIS official examples

## Brand

- Personality: calm, operational, trustworthy, beginner-friendly, evidence-first
- Trust signals: explicit data date, source, execution mode, stage status, order status, and safety state
- Avoid: casino aesthetics, neon overload, unexplained financial jargon, fake live indicators, profit celebration, accepted-order-as-fill wording, and realistic seeded account data

## Product goals

- Goals: prove that one learner-owned strategy run completed; make system state and failures understandable; distinguish mock, paper, blocked, and real states; help learners decide the next safe action
- Non-goals: promise returns, reproduce a brokerage terminal, or expose raw credentials/account payloads
- Success signals: a learner can answer what data was used, where the pipeline stopped, what decision was made, whether an order filled, and whether each message channel delivered

## Personas and jobs

- Primary personas: non-developer investor with a strategy idea; vibe-coding beginner; instructor demonstrating the system live
- User jobs: verify a complete run, understand a decision, inspect paper-order state, confirm notifications, review lessons, and find the next corrective action
- Key contexts of use: weekend classroom with latest prior business-day data; local laptop demo; optional KIS paper account; desktop presentation and mobile spot-check

## Information architecture

- Primary navigation: one scrolling execution story for the latest run; run selector is a later enhancement
- Core routes/screens: `/` operations dashboard, `/api/dashboard` run-scoped JSON, `/api/data` compatibility JSON
- Content hierarchy: truth bar → pipeline timeline → notification health → order truth → portfolio → analysis → lessons

## Design principles

- Truth before decoration: show source, date, mode, and status before scores or holdings.
- One run, one story: all visible sections resolve to the same `run_id`.
- Decision is not execution: blocked, accepted, partial, filled, rejected, and cancelled are distinct.
- Failure is actionable: errors state the failed stage and safe fallback without exposing secrets.
- Progressive detail: the main status is scannable; six-section analysis and technical details are expandable.
- Tradeoff: preserve the build-free single-page teaching surface even when a component framework would scale further.

## Visual language

- Color: deep neutral navy background; blue for information; green only for completed/filled; amber for decision-only, stale, partial, or paper; red for failed/rejected/live-blocked; gray for skipped/disabled
- Typography: local system Korean sans-serif with tabular system monospace for IDs, prices, dates, and quantities; no remote font dependency
- Spacing/layout rhythm: 4/8px base rhythm, 16–24px card padding, generous section separation
- Shape/radius/elevation: 10–14px radius, thin borders, minimal shadow, no glowing speculative effects
- Motion: short status transitions only; polling updates must not shift layout; respect reduced motion
- Imagery/iconography: small semantic symbols paired with text; no decorative stock photography

## Components

- Existing components to reuse: badge, score bar, table, expandable six-section analysis, lesson card
- New/changed components: truth bar, run-status banner, pipeline timeline, channel delivery cards, order-state table, portfolio snapshot, stale-data warning, safe empty state
- Variants and states: mock/paper/live-blocked/real; open/closed/unknown market; queued/sent/failed/skipped delivery; blocked/accepted/unfilled/partial/filled/rejected/cancelled/unknown order
- Token/component ownership: CSS custom properties and HTML templates remain owned by `dashboard.py`; state vocabulary is owned by runtime/domain modules

## Accessibility

- Target standard: WCAG 2.1 AA for contrast and keyboard-visible interactions
- Keyboard/focus behavior: visible focus rings for links, buttons, details, and controls; logical document order
- Contrast/readability: no color-only status; minimum readable body size; tabular numbers; Korean labels before technical codes
- Screen-reader semantics: headings follow hierarchy; tables include headers; status changes use polite live regions when updated
- Reduced motion and sensory considerations: honor `prefers-reduced-motion`; avoid flashing and pulsing live indicators

## Responsive behavior

- Supported breakpoints/devices: 1440×900, 1280×720, 768px tablet, 390×844 mobile
- Layout adaptations: summary cards wrap; timeline becomes vertical; wide tables use contained horizontal scroll or stacked rows; header metadata wraps
- Touch/hover differences: all information remains available without hover; touch targets are at least 40px where interactive

## Interaction states

- Loading: skeleton/status copy without inventing values
- Empty: explain that no pipeline run exists and provide a coding-agent prompt to run the demo
- Error: identify failed stage and safe fallback; keep last confirmed data visibly dated
- Success: show completed run and confirmed delivery/order state without celebratory profit framing
- Disabled: show channel or broker as not configured, not failed
- Offline/slow network: retain last confirmed run, mark refresh failure, and never relabel stale content as current

## Content voice

- Tone: direct, calm Korean suitable for a first-time investor/developer
- Terminology: use `판단`, `주문 접수`, `부분 체결`, `체결`, `차단`, and `데이터 기준일` consistently
- Microcopy rules: every market/order status includes a plain-language consequence; technical IDs are secondary; never say `실시간` unless the value is actually streaming/current

## Implementation constraints

- Framework/styling system: FastAPI plus build-free single HTML/CSS/vanilla JS
- Design-token constraints: reuse a compact semantic token set; do not create a second theme layer
- Performance constraints: local response should remain lightweight; poll run-scoped JSON instead of reloading the full page
- Compatibility constraints: keyless demo and Python 3.10+, no mandatory frontend toolchain, localhost binding
- Test/screenshot expectations: API/HTML unit tests plus visual verdicts for empty, mock, closed-market, channel-failure, partial-fill, failed-stage, desktop, and mobile fixtures

## Open questions

- None blocking. A historical run selector and live WebSocket updates are deferred enhancements.
