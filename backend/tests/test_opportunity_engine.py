from __future__ import annotations

import json
from datetime import UTC, datetime

from app.services.market_data import PolymarketDataProvider
from app.services.opportunities import OpportunityEngine
from app.services.paper import PaperTradingService
from app.services.risk import RiskManager


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, active_events, active_books, closed_events=None, closed_books=None):
        self.active_events = active_events
        self.active_books = active_books
        self.closed_events = closed_events or []
        self.closed_books = closed_books or []

    def get(self, url, params=None, timeout=None):
        _ = timeout
        if url.endswith("/events"):
            if params and params.get("closed") == "true":
                return FakeResponse(self.closed_events)
            return FakeResponse(self.active_events)
        raise AssertionError(f"Unexpected GET {url}")

    def post(self, url, json=None, timeout=None):
        _ = json, timeout
        if url.endswith("/books"):
            payload = list(self.active_books)
            if self.closed_books:
                payload.extend(self.closed_books)
            return FakeResponse(payload)
        raise AssertionError(f"Unexpected POST {url}")


def make_live_provider():
    active_events = [
        {
            "id": "1000",
            "title": "Harvey Weinstein prison time?",
            "slug": "harvey-weinstein-prison-time",
            "subcategory": "news",
            "liquidity": 15000,
            "volume": 600000,
            "negRisk": True,
            "markets": [
                _market_payload("1", "No prison time", "Will Harvey Weinstein be sentenced to no prison time?", "0.27", "0.26", "yes-1", "no-1", neg_risk=True),
                _market_payload("2", "<5 years", "Will Harvey Weinstein be sentenced to less than 5 years in prison?", "0.31", "0.30", "yes-2", "no-2", neg_risk=True),
                _market_payload("3", "5-10 years", "Will Harvey Weinstein be sentenced to between 5 and 10 years in prison?", "0.34", "0.33", "yes-3", "no-3", neg_risk=True),
            ],
        },
        {
            "id": "2000",
            "title": "Kraken IPO by ___ ?",
            "slug": "kraken-ipo-by",
            "subcategory": "business",
            "liquidity": 50000,
            "volume": 1400000,
            "negRisk": False,
            "markets": [
                _market_payload("10", "December 31, 2026", "Kraken IPO by December 31, 2026?", "0.52", "0.50", "yes-10", "no-10", end_date="2026-12-31T12:00:00Z"),
                _market_payload("11", "December 31, 2025", "Kraken IPO in 2025?", "0.64", "0.62", "yes-11", "no-11", end_date="2025-12-31T12:00:00Z"),
            ],
        },
    ]
    active_books = [
        _book_payload("yes-1", ask_price=0.27, bid_price=0.26),
        _book_payload("yes-2", ask_price=0.31, bid_price=0.30),
        _book_payload("yes-3", ask_price=0.34, bid_price=0.33),
        _book_payload("yes-10", ask_price=0.52, bid_price=0.50),
        _book_payload("yes-11", ask_price=0.64, bid_price=0.62),
    ]
    provider = PolymarketDataProvider()
    provider.session = FakeSession(active_events=active_events, active_books=active_books)
    return provider


def make_settlement_provider():
    active_events = [
        {
            "id": "2000",
            "title": "Kraken IPO by ___ ?",
            "slug": "kraken-ipo-by",
            "subcategory": "business",
            "liquidity": 50000,
            "volume": 1400000,
            "negRisk": False,
            "markets": [
                _market_payload("10", "December 31, 2026", "Kraken IPO by December 31, 2026?", "0.52", "0.50", "yes-10", "no-10", end_date="2026-12-31T12:00:00Z"),
                _market_payload("11", "December 31, 2025", "Kraken IPO in 2025?", "0.64", "0.62", "yes-11", "no-11", end_date="2025-12-31T12:00:00Z"),
            ],
        }
    ]
    active_books = [
        _book_payload("yes-10", ask_price=0.52, bid_price=0.50),
        _book_payload("yes-11", ask_price=0.64, bid_price=0.62),
    ]
    closed_events = [
        {
            "id": "2000",
            "title": "Kraken IPO by ___ ?",
            "slug": "kraken-ipo-by",
            "subcategory": "business",
            "liquidity": 50000,
            "volume": 1400000,
            "negRisk": False,
            "markets": [
                _market_payload(
                    "10",
                    "December 31, 2026",
                    "Kraken IPO by December 31, 2026?",
                    "1.0",
                    "0.99",
                    "yes-10",
                    "no-10",
                    active=False,
                    closed=True,
                    outcome_prices=["1", "0"],
                    end_date="2026-12-31T12:00:00Z",
                ),
            ],
        }
    ]
    closed_books = [_book_payload("yes-10", ask_price=0.99, bid_price=0.98)]
    provider = PolymarketDataProvider()
    provider.session = FakeSession(
        active_events=active_events,
        active_books=active_books,
        closed_events=closed_events,
        closed_books=closed_books,
    )
    return provider


def _market_payload(
    market_id: str,
    group_title: str,
    question: str,
    ask: str,
    bid: str,
    yes_token: str,
    no_token: str,
    *,
    neg_risk: bool = False,
    active: bool = True,
    closed: bool = False,
    outcome_prices: list[str] | None = None,
    end_date: str | None = None,
):
    return {
        "id": market_id,
        "question": question,
        "groupItemTitle": group_title,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(outcome_prices or [ask, str(1 - float(ask))]),
        "clobTokenIds": json.dumps([yes_token, no_token]),
        "enableOrderBook": True,
        "acceptingOrders": active and not closed,
        "active": active,
        "closed": closed,
        "closedTime": "2026-12-31T13:00:00Z" if closed else None,
        "bestAsk": float(ask),
        "bestBid": float(bid),
        "spread": round(float(ask) - float(bid), 4),
        "liquidityNum": 5000,
        "volumeNum": 120000,
        "oneDayPriceChange": 0.02,
        "orderMinSize": 5,
        "negRisk": neg_risk,
        "endDate": end_date or f"2026-12-{int(market_id):02d}T12:00:00Z",
    }


def _book_payload(token_id: str, *, ask_price: float, bid_price: float):
    timestamp_ms = int(datetime.now(UTC).timestamp() * 1000)
    return {
        "asset_id": token_id,
        "timestamp": str(timestamp_ms),
        "asks": [
            {"price": f"{ask_price + 0.04:.3f}", "size": "50"},
            {"price": f"{ask_price:.3f}", "size": "80"},
        ],
        "bids": [
            {"price": f"{bid_price:.3f}", "size": "70"},
            {"price": f"{max(bid_price - 0.02, 0.001):.3f}", "size": "60"},
        ],
    }


def test_live_snapshot_derives_real_groupings(db_session):
    provider = make_live_provider()
    snapshot = provider.load_current_snapshot(force_refresh=True)

    assert len(snapshot.outcome_groups) == 1
    assert len(snapshot.relations) == 1
    assert snapshot.outcome_groups[0].name == "Harvey Weinstein prison time?"
    assert snapshot.relations[0].broader_market_id == "10"


def test_engine_finds_live_polymarket_opportunities(db_session):
    provider = make_live_provider()
    risk_manager = RiskManager()
    engine = OpportunityEngine(risk_manager=risk_manager)
    risk_manager.get_or_create_settings(db_session)

    scan = engine.scan(snapshot=provider.load_current_snapshot(force_refresh=True), db=db_session)
    names = [item.name for item in scan.opportunities]

    assert "Harvey Weinstein prison time? basket" in names
    assert any(item.strategy_type == "cross_market" for item in scan.opportunities)
    assert scan.opportunities[0].strategy_type == "sum_to_one"


def test_paper_trade_refresh_uses_live_resolution(db_session):
    provider = make_live_provider()
    risk_manager = RiskManager()
    engine = OpportunityEngine(risk_manager=risk_manager)
    paper = PaperTradingService(provider=provider, risk_manager=risk_manager)
    risk_manager.get_or_create_settings(db_session)

    scan = engine.scan(snapshot=provider.load_current_snapshot(force_refresh=True), db=db_session)
    relation = next(item for item in scan.opportunities if item.strategy_type == "cross_market")
    trade = paper.create_manual_trade(db_session, relation)
    assert trade.status == "OPEN"

    settlement_provider = make_settlement_provider()
    paper.provider = settlement_provider
    summary = paper.refresh_trade_statuses(db_session)
    refreshed = paper.list_recent_trades(db_session, limit=1)[0]

    assert summary["resolved"] == 1
    assert refreshed.status == "CLOSED"
    assert refreshed.realized_pnl is not None
