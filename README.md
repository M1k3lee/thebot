# Plain Market

Plain Market is a beginner-first prediction-market assistant for small capital. It does not try to predict everything. It looks for a narrow set of explainable setups, tells the user when to do nothing, defaults to paper trading, and only considers live mode after paper results clear a safety gate.

## A. Recommended product design

The recommended concept is a "plain-English opportunity coach" rather than a trading terminal.

- One dashboard shows only the best current ideas.
- Each idea answers six questions: what it is, why it may exist, what could go wrong, how much edge may remain after costs, how small the size should be, and whether the sensible action is `Watch`, `Simulate`, or `Small Trade`.
- The system favors two simple strategy classes first:
  - Sum-to-one basket mispricing across mutually exclusive outcomes.
  - Cross-market monotonic inconsistencies that can be explained in one sentence.
- Paper trading is the default path. Live mode is gated, optional, and still risk-limited even after the gate is passed.

## B. Why this fits basic users

- It removes most market complexity instead of exposing it.
- It never asks a beginner to size a trade from scratch.
- It explains uncertainty directly instead of pretending edge means certainty.
- It gives users permission to skip weak setups.
- It keeps the number of screens low and the language plain.

## C. MVP feature list

- Current opportunity scan from a sample market-data provider.
- Sum-to-one basket detection.
- Cross-market inconsistency detection.
- Fee, slippage, fill-probability, freshness, and liquidity checks.
- Ranking by quality and safety.
- One dashboard page.
- One detail page per opportunity.
- One settings page.
- Manual paper-trade creation.
- Historical replay mode.
- Paper performance tracking.
- Live-mode eligibility gate.
- Daily loss cap, per-market cap, consecutive-loss stop, and volatility stop logic.
- Audit events for settings changes, replay runs, and paper-trade creation.
- JSON API endpoints for dashboard and opportunity detail.

## D. User flow

1. Open the dashboard.
2. See either `No good trade right now` or a short list of current ideas.
3. Open one idea to read the plain-English explanation.
4. Add the idea to paper trading first.
5. Run replay from Settings to build a small validation history.
6. Review paper results, win rate, edge capture, and safety checks.
7. Attempt to enable live mode only if the gate passes.
8. Continue using the same dashboard, with the app still preferring `Simulate` unless the setup is unusually clean.

## E. Information architecture

- `/`
  - Dashboard
  - Best current opportunities
  - Rejected-idea reasons
  - Recent paper-trading activity
- `/opportunities/{id}`
  - Opportunity detail
  - Plain-English explanation blocks
  - Assumptions and safety checks
  - Paper-trade action
  - Hidden advanced section
- `/settings`
  - Risk defaults
  - Replay and validation
  - Live-mode gate
  - Safety policy summary
- `/api/dashboard`
  - JSON scan summary
- `/api/opportunities/{id}`
  - JSON detail for one opportunity

## F. Wireframe-level UI description

### Dashboard

Top section:

- Large headline with the best current advice.
- Mode badge: `Paper only` by default.
- Data freshness and market-count chips.

Opportunity cards:

- Opportunity name
- Strategy type
- One-sentence explanation
- Quality score
- Estimated edge after costs
- Maximum suggested size
- Worst-case loss
- Action badge
- Liquidity, freshness, and fill-probability labels

Lower section:

- Rejected ideas with reasons
- Recent paper-trading history

### Opportunity detail

- Large title and action badge
- Summary metrics
- Plain-English sections:
  - Why this may work
  - What could go wrong
  - Why the app is not fully certain
  - If the market moves against you
- Assumptions section:
  - Fees
  - Slippage
  - Fill probability
  - Liquidity quality
  - Data freshness
  - Volatility
- One main call to action: `Add to paper trading`
- Advanced section hidden behind a toggle

### Settings

- Risk limits form
- Replay runner
- Paper-performance summary
- Live-mode gate checklist
- Explicit note that this MVP does not send real market orders

## G. System architecture

Low-cost architecture:

- Backend: FastAPI
- Storage: SQLite
- Frontend: server-rendered Jinja templates with a small CSS/JS layer
- Data source: local JSON sample provider
- Logging: rotating file log plus audit-events table

Request path:

1. Route loads current sample snapshot.
2. Opportunity engine computes clean setups and rejected ideas.
3. Risk manager applies sizing and action rules using stored settings and paper stats.
4. Template renders plain-English cards and detail views.
5. Paper-trading actions and replay runs are persisted in SQLite.

## H. Folder structure

```text
.
|-- README.md
|-- .gitignore
`-- backend
    |-- requirements.txt
    |-- app
    |   |-- main.py
    |   |-- db.py
    |   |-- models.py
    |   |-- core
    |   |   `-- config.py
    |   |-- data
    |   |   |-- current_snapshot.json
    |   |   `-- historical_snapshots.json
    |   |-- services
    |   |   |-- market_data.py
    |   |   |-- opportunities.py
    |   |   |-- paper.py
    |   |   `-- risk.py
    |   |-- static
    |   |   |-- app.js
    |   |   `-- styles.css
    |   `-- templates
    |       |-- base.html
    |       |-- dashboard.html
    |       |-- opportunity.html
    |       `-- settings.html
    `-- tests
        |-- conftest.py
        `-- test_opportunity_engine.py
```

## I. Full implementation plan

Completed MVP plan:

1. Define a constrained product scope around two explainable strategy classes.
2. Build a local market-data adapter so the app works offline and cheaply.
3. Implement opportunity detection with fee, slippage, liquidity, freshness, and volatility filters.
4. Add a risk manager that sizes trades conservatively and decides between `Watch`, `Simulate`, and `Small Trade`.
5. Build a paper-trading service and replay engine.
6. Create the dashboard, detail page, and settings page.
7. Add tests for scan quality, replay generation, and live-mode gating.
8. Document setup, architecture, assumptions, and limitations.

## J. Backend code

Backend responsibilities are split across a few small modules:

- `backend/app/main.py`
  - FastAPI routes, template rendering, JSON endpoints
- `backend/app/models.py`
  - SQLite persistence models for settings, paper trades, and audit events
- `backend/app/services/market_data.py`
  - Snapshot parsing and sample provider
- `backend/app/services/opportunities.py`
  - Opportunity scoring, ranking, rejection, and explainability fields
- `backend/app/services/risk.py`
  - Sizing, live gate, kill-switch checks, and paper stats
- `backend/app/services/paper.py`
  - Manual paper trade creation and replay settlement

## K. Frontend code

Frontend is intentionally lightweight:

- `backend/app/templates/*.html`
  - Server-rendered pages with minimal cognitive load
- `backend/app/static/styles.css`
  - Calm card-based layout with large labels and soft emphasis
- `backend/app/static/app.js`
  - Toggle advanced details and confirm risky settings actions

This keeps infrastructure cost and setup friction low while still delivering a usable product.

## L. Sample opportunity-scoring logic

The scoring model is deliberately simple and explainable.

Sum-to-one basket:

- Compute total basket cost.
- Add fees and slippage.
- Reject if total cost after costs is not below $1 payout.
- Score using:
  - edge after costs
  - weakest liquidity leg
  - fill probability
  - freshness
  - volatility
  - safety bonus for the basket structure

Cross-market inconsistency:

- Compare a broader market against a narrower market that it logically contains.
- Compute the price gap.
- Subtract fees and slippage.
- Reject if the remaining gap is too small.
- Score using:
  - gap after costs
  - raw logic gap
  - liquidity
  - fill probability
  - freshness
  - volatility

## M. Risk-management logic

Risk rules in this MVP:

- Paper trading by default.
- Suggested stake is capped by:
  - bankroll share
  - daily loss cap
  - per-market loss cap
  - available liquidity
  - fill probability
- The app falls back to `Watch` if:
  - edge is too small
  - fill odds are too weak
  - data is stale
  - volatility is too high
  - kill-switch conditions are active
- Live-mode gate requires:
  - at least 5 closed paper trades
  - at least 50% win rate
  - non-negative paper P&L
  - at least 0.35 edge-capture ratio
  - no current kill-switch condition

Explicit exclusions:

- No leverage
- No martingale
- No doubling down
- No averaging down guidance

## N. Paper-trading logic

- Manual paper trade:
  - stores opportunity snapshot, expected edge, suggested size, assumptions, and notes
- Replay mode:
  - runs the engine across historical snapshots
  - creates closed paper trades for qualifying opportunities
  - compares expected edge with realized P&L
- Paper stats:
  - open trades
  - closed trades
  - win rate
  - total P&L
  - expected-profit total
  - edge-capture ratio

## O. Example UI copy in plain English

Examples used in the app:

- `No good trade right now.`
- `Buying every outcome costs 95.0% before costs, so the whole basket still sits below 100%.`
- `Exactly one outcome can win here. If the full basket costs less than a full $1 payout after costs, the gap is a real cushion.`
- `This is not a locked-in arbitrage by itself. The broader market can still finish NO and lose the full stake.`
- `Paper mode is safer until the signal proves itself.`
- `If the price drops, stop at your size cap. Do not average down and do not increase risk.`

## P. Setup instructions, assumptions, and limitations

### Local setup

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Run tests

```bash
cd backend
python -m pytest
```

### Assumptions

- The current build uses local sample data, not a live exchange adapter.
- Costs are estimated from simple fee and slippage assumptions.
- Fill probability is heuristic, not a market microstructure model.
- Live mode is a gated UI state in this MVP, not a real brokerage/exchange execution bridge.

### Limitations

- No real market API adapter yet.
- No authentication or multi-user support.
- No background scheduler.
- No actual live execution connector.
- No passive market making in the MVP because it adds too much operational complexity for a beginner-first release.

### Verification completed

- `python -m pytest`
- FastAPI smoke checks for `/`, `/settings`, `/api/dashboard`, and `/healthz`
