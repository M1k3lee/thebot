# Plain Market

Plain Market is a live-data Polymarket assistant for cautious users with small capital.

It does not promise profit. It scans real Polymarket events, looks for simple and explainable inconsistencies, estimates edge after costs, and defaults to paper trading. The product is designed to say `No good trade right now` when the live book does not support a clean opportunity.

## What Changed

This build is now live-only.

- No sample market data
- No fake replay data
- No historical fixture snapshots
- Real-time scan source: Polymarket Gamma API + CLOB order books

## Product Concept

The right concept for this use case is not a trading terminal and not an AI prediction engine.

It is a narrow Polymarket scanner that focuses on:

- Negative-risk baskets on live mutually exclusive Polymarket events
- Cross-market date-ladder inconsistencies where the later market should not price below the earlier one
- Small-size suggestions only
- Paper trading first
- Plain-English reasons for every recommendation

This is the most realistic path to a trustworthy beginner product because the edge comes from market structure, not from pretending we can predict the world better than everyone else.

## Current MVP

### Included

- Live Polymarket event discovery
- Live CLOB order-book reads
- Negative-risk basket detection
- Date-ladder monotonicity detection
- Fee, slippage, liquidity, freshness, and volatility filters
- Conservative sizing
- Paper trade creation from live opportunities
- Paper trade refresh against live or closed Polymarket markets
- Live-mode gate based on actual paper results
- Dashboard, opportunity detail page, and settings page

### Not Included

- Real order placement
- Authenticated Polymarket trading
- Leverage
- Martingale or averaging down
- Fake backtests
- Synthetic replays

## Data Sources

The app uses:

- Polymarket Gamma API for live event and market discovery
- Polymarket CLOB API for live order-book depth

Relevant official docs:

- [Polymarket docs](https://docs.polymarket.com/)
- [Gamma overview](https://docs.polymarket.com/developers/gamma-markets-api/overview)
- [CLOB overview](https://docs.polymarket.com/developers/CLOB/introduction)
- [Order book endpoint](https://docs.polymarket.com/developers/CLOB/orders/get-order-book)

## Opportunity Logic

### 1. Negative-risk baskets

For live events marked as `negRisk`, the scanner sums the live YES-side cost across the event’s mutually exclusive buckets.

The app only keeps the basket if:

- the basket still costs less than the implied $1 payout after slippage and fees
- the book is deep enough for a small fill
- spreads are not too wide
- data is fresh enough

### 2. Date-ladder inconsistencies

For live series like `X by ___ ?`, the later date should not trade below the earlier date.

The app compares adjacent live markets in the ladder and only keeps the idea if the price gap survives:

- fees
- slippage
- liquidity checks
- volatility checks

## Risk Rules

- Paper trading is the default
- Live mode is off by default
- Suggested size is capped by bankroll share, daily loss cap, per-market cap, and live book depth
- Weak edges are rejected
- Thin books are rejected
- Stale data is rejected
- High-volatility setups are rejected
- No leverage
- No doubling down
- No martingale

## Architecture

Low-cost stack:

- Backend: FastAPI
- UI: server-rendered Jinja templates
- Storage: SQLite
- Market data: live Polymarket public APIs
- Logs: rotating log file plus audit events in SQLite

## Folder Layout

```text
.
|-- README.md
|-- index.html
|-- .gitignore
`-- backend
    |-- requirements.txt
    |-- app
    |   |-- main.py
    |   |-- db.py
    |   |-- models.py
    |   |-- core
    |   |   `-- config.py
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

## Local Setup

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Testing

```bash
cd backend
python -m pytest
```

The tests mock Polymarket API responses so the code can be verified without depending on external uptime during CI or local test runs.

## Practical Limitation

This app can help identify structurally sensible Polymarket opportunities. It cannot guarantee that any opportunity will make money.

The realistic path is:

1. Scan live Polymarket books
2. Paper trade only
3. Let a real paper history build over time
4. Keep live mode locked until the history is good enough
5. Only then consider adding authenticated order placement

## Verification Completed

- `python -m pytest`
- FastAPI smoke checks for `/`, `/settings`, `/api/dashboard`, and `/healthz`
