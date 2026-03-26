from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from app.core.config import settings


@dataclass(slots=True)
class OrderLevel:
    price: float
    size: float


@dataclass(slots=True)
class OrderBookSummary:
    token_id: str
    best_bid: float
    best_ask: float
    midpoint: float
    spread: float
    ask_depth_at_best: float
    bid_depth_at_best: float
    cumulative_ask_depth: float
    average_ask_price_for_target: float
    average_bid_price_for_target: float
    ask_levels: list[OrderLevel]
    bid_levels: list[OrderLevel]
    freshness_seconds: int


@dataclass(slots=True)
class MarketQuote:
    id: str
    event_id: str
    event_title: str
    event_slug: str
    question: str
    short_name: str
    category: str
    end_date: str
    buy_yes_price: float
    sell_yes_price: float
    best_bid: float
    best_ask: float
    fee_bps: int
    liquidity_score: float
    available_size: float
    freshness_seconds: int
    volatility_score: float
    volume_num: float
    liquidity_num: float
    yes_token_id: str
    no_token_id: str
    group_item_title: str
    neg_risk: bool
    accepting_orders: bool
    order_min_size: float
    one_day_price_change: float
    settled_yes: bool | None = None

    @property
    def spread(self) -> float:
        return max(self.best_ask - self.best_bid, 0.0)

    @property
    def midpoint(self) -> float:
        return round((self.best_ask + self.best_bid) / 2, 4) if self.best_bid and self.best_ask else 0.0


@dataclass(slots=True)
class MarketEvent:
    id: str
    title: str
    slug: str
    category: str
    subcategory: str
    liquidity: float
    volume: float
    neg_risk: bool
    markets: list[MarketQuote] = field(default_factory=list)


@dataclass(slots=True)
class OutcomeGroup:
    id: str
    name: str
    event_id: str
    market_ids: list[str]
    note: str


@dataclass(slots=True)
class MarketRelation:
    id: str
    name: str
    event_id: str
    broader_market_id: str
    narrower_market_id: str
    explanation: str


@dataclass(slots=True)
class MarketSnapshot:
    snapshot_id: str
    as_of: str
    markets: dict[str, MarketQuote]
    events: list[MarketEvent] = field(default_factory=list)
    outcome_groups: list[OutcomeGroup] = field(default_factory=list)
    relations: list[MarketRelation] = field(default_factory=list)


class MarketDataUnavailableError(RuntimeError):
    pass


class PolymarketDataProvider:
    """Loads live Polymarket events from Gamma and order books from the CLOB."""

    def __init__(
        self,
        gamma_base_url: str | None = None,
        clob_base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.gamma_base_url = gamma_base_url or settings.polymarket_gamma_base_url
        self.clob_base_url = clob_base_url or settings.polymarket_clob_base_url
        self.timeout_seconds = timeout_seconds or settings.polymarket_timeout_seconds
        self.session = requests.Session()
        self._cache: MarketSnapshot | None = None
        self._cache_loaded_at: datetime | None = None

    def load_current_snapshot(self, force_refresh: bool = False) -> MarketSnapshot:
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._cache is not None
            and self._cache_loaded_at is not None
            and (now - self._cache_loaded_at).total_seconds() < settings.polymarket_cache_ttl_seconds
        ):
            return self._cache

        events_payload = self._fetch_events()
        event_market_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        yes_token_ids: list[str] = []
        for event in events_payload:
            if float(event.get("liquidity") or 0.0) < settings.min_event_liquidity:
                continue
            for market in event.get("markets", []):
                if not self._is_supported_market(market):
                    continue
                event_market_rows.append((event, market))
                yes_token_ids.append(self._extract_token_ids(market)[0])

        books = self._fetch_books(yes_token_ids)
        markets: dict[str, MarketQuote] = {}
        events: dict[str, MarketEvent] = {}

        for event_payload, market_payload in event_market_rows:
            yes_token_id, no_token_id = self._extract_token_ids(market_payload)
            book_summary = books.get(yes_token_id)
            if not book_summary or len(book_summary.ask_levels) < settings.min_book_levels:
                continue

            event_id = str(event_payload["id"])
            event_obj = events.setdefault(
                event_id,
                MarketEvent(
                    id=event_id,
                    title=event_payload.get("title") or "Untitled event",
                    slug=event_payload.get("slug") or "",
                    category=event_payload.get("category") or "",
                    subcategory=event_payload.get("subcategory") or "",
                    liquidity=float(event_payload.get("liquidity") or 0.0),
                    volume=float(event_payload.get("volume") or 0.0),
                    neg_risk=bool(event_payload.get("negRisk")),
                    markets=[],
                ),
            )

            market = self._build_market_quote(
                event=event_obj,
                market_payload=market_payload,
                book_summary=book_summary,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )
            if market.liquidity_num < settings.min_market_liquidity:
                continue
            markets[market.id] = market
            event_obj.markets.append(market)

        event_list = [event for event in events.values() if len(event.markets) >= 2]
        outcome_groups = self._derive_outcome_groups(event_list)
        relations = self._derive_relations(event_list)
        snapshot = MarketSnapshot(
            snapshot_id=f"polymarket-{int(now.timestamp())}",
            as_of=now.isoformat(),
            markets=markets,
            events=event_list,
            outcome_groups=outcome_groups,
            relations=relations,
        )
        self._cache = snapshot
        self._cache_loaded_at = now
        return snapshot

    def load_market_map(self, *, include_closed: bool = True) -> dict[str, MarketQuote]:
        now = datetime.now(UTC)
        events_payload = self._fetch_events(active_only=True, include_closed=False, pages=3)
        if include_closed:
            events_payload.extend(self._fetch_events(active_only=False, include_closed=True, pages=3))
        event_market_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        yes_token_ids: list[str] = []
        for event in events_payload:
            for market in event.get("markets", []):
                if not self._is_supported_market(market, include_closed=include_closed):
                    continue
                event_market_rows.append((event, market))
                yes_token_ids.append(self._extract_token_ids(market)[0])

        books = self._fetch_books(yes_token_ids)
        markets: dict[str, MarketQuote] = {}
        for event_payload, market_payload in event_market_rows:
            yes_token_id, no_token_id = self._extract_token_ids(market_payload)
            book_summary = books.get(yes_token_id)
            if book_summary is None:
                book_summary = OrderBookSummary(
                    token_id=yes_token_id,
                    best_bid=float(market_payload.get("bestBid") or 0.0),
                    best_ask=float(market_payload.get("bestAsk") or market_payload.get("lastTradePrice") or 0.0),
                    midpoint=float(market_payload.get("lastTradePrice") or 0.0),
                    spread=float(market_payload.get("spread") or 0.0),
                    ask_depth_at_best=0.0,
                    bid_depth_at_best=0.0,
                    cumulative_ask_depth=0.0,
                    average_ask_price_for_target=float(market_payload.get("bestAsk") or market_payload.get("lastTradePrice") or 0.0),
                    average_bid_price_for_target=float(market_payload.get("bestBid") or market_payload.get("lastTradePrice") or 0.0),
                    ask_levels=[],
                    bid_levels=[],
                    freshness_seconds=max(int((now - now).total_seconds()), 0),
                )
            event_obj = MarketEvent(
                id=str(event_payload["id"]),
                title=event_payload.get("title") or "Untitled event",
                slug=event_payload.get("slug") or "",
                category=event_payload.get("category") or "",
                subcategory=event_payload.get("subcategory") or "",
                liquidity=float(event_payload.get("liquidity") or 0.0),
                volume=float(event_payload.get("volume") or 0.0),
                neg_risk=bool(event_payload.get("negRisk")),
            )
            market = self._build_market_quote(
                event=event_obj,
                market_payload=market_payload,
                book_summary=book_summary,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )
            if include_closed and market_payload.get("closed") and market_payload.get("closedTime") and market_payload.get("outcomePrices"):
                outcome_prices = json.loads(market_payload["outcomePrices"])
                market.settled_yes = float(outcome_prices[0]) >= 0.999
            markets[market.id] = market
        return markets

    def _fetch_events(
        self,
        *,
        active_only: bool = True,
        include_closed: bool = False,
        pages: int | None = None,
    ) -> list[dict[str, Any]]:
        all_events: list[dict[str, Any]] = []
        limit = settings.polymarket_events_limit
        total_pages = pages or settings.polymarket_scan_pages
        for page in range(total_pages):
            params = {
                "limit": limit,
                "offset": page * limit,
            }
            if active_only:
                params["active"] = "true"
                params["closed"] = "false"
            elif include_closed:
                params["closed"] = "true"
            response = self.session.get(
                f"{self.gamma_base_url}/events",
                params=params,
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise MarketDataUnavailableError("Unable to load Polymarket events right now.") from exc
            payload = response.json()
            if not payload:
                break
            all_events.extend(payload)
            if len(payload) < limit:
                break
        return all_events

    def _fetch_books(self, token_ids: list[str]) -> dict[str, OrderBookSummary]:
        results: dict[str, OrderBookSummary] = {}
        for start in range(0, len(token_ids), settings.polymarket_book_batch_size):
            chunk = token_ids[start : start + settings.polymarket_book_batch_size]
            response = self.session.post(
                f"{self.clob_base_url}/books",
                json=[{"token_id": token_id} for token_id in chunk],
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise MarketDataUnavailableError("Unable to load Polymarket order books right now.") from exc
            for row in response.json():
                summary = self._parse_book(row)
                results[summary.token_id] = summary
        return results

    @staticmethod
    def _parse_book(payload: dict[str, Any]) -> OrderBookSummary:
        now = datetime.now(UTC)
        asks = sorted(
            [OrderLevel(price=float(level["price"]), size=float(level["size"])) for level in payload.get("asks", []) if float(level["size"]) > 0],
            key=lambda level: level.price,
        )
        bids = sorted(
            [OrderLevel(price=float(level["price"]), size=float(level["size"])) for level in payload.get("bids", []) if float(level["size"]) > 0],
            key=lambda level: level.price,
            reverse=True,
        )
        best_ask = asks[0].price if asks else 0.0
        best_bid = bids[0].price if bids else 0.0
        midpoint = round((best_ask + best_bid) / 2, 4) if best_ask and best_bid else best_ask or best_bid
        timestamp_ms = int(payload.get("timestamp") or 0)
        freshness_seconds = 0
        if timestamp_ms:
            fresh_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
            freshness_seconds = max(int((now - fresh_at).total_seconds()), 0)

        return OrderBookSummary(
            token_id=payload["asset_id"],
            best_bid=best_bid,
            best_ask=best_ask,
            midpoint=midpoint,
            spread=max(best_ask - best_bid, 0.0),
            ask_depth_at_best=asks[0].size if asks else 0.0,
            bid_depth_at_best=bids[0].size if bids else 0.0,
            cumulative_ask_depth=sum(level.size for level in asks if level.price <= best_ask + 0.01) if asks else 0.0,
            average_ask_price_for_target=_weighted_average_price(asks, settings.polymarket_target_shares, side="buy"),
            average_bid_price_for_target=_weighted_average_price(bids, settings.polymarket_target_shares, side="sell"),
            ask_levels=asks,
            bid_levels=bids,
            freshness_seconds=freshness_seconds,
        )

    @staticmethod
    def _extract_token_ids(market_payload: dict[str, Any]) -> tuple[str, str]:
        tokens = json.loads(market_payload["clobTokenIds"])
        return str(tokens[0]), str(tokens[1])

    @staticmethod
    def _is_supported_market(market_payload: dict[str, Any], include_closed: bool = False) -> bool:
        if not market_payload.get("enableOrderBook"):
            return False
        if not include_closed and market_payload.get("closed"):
            return False
        if not market_payload.get("active") and not include_closed:
            return False
        if market_payload.get("outcomes") is None or market_payload.get("clobTokenIds") is None:
            return False
        outcomes = json.loads(market_payload["outcomes"])
        return len(outcomes) == 2 and outcomes[0] == "Yes" and outcomes[1] == "No"

    def _build_market_quote(
        self,
        *,
        event: MarketEvent,
        market_payload: dict[str, Any],
        book_summary: OrderBookSummary,
        yes_token_id: str,
        no_token_id: str,
    ) -> MarketQuote:
        liquidity_num = float(market_payload.get("liquidityNum") or market_payload.get("liquidity") or 0.0)
        volume_num = float(market_payload.get("volumeNum") or market_payload.get("volume") or 0.0)
        one_day_change = abs(float(market_payload.get("oneDayPriceChange") or 0.0))
        buy_yes = book_summary.average_ask_price_for_target or float(market_payload.get("bestAsk") or 0.0)
        sell_yes = book_summary.average_bid_price_for_target or float(market_payload.get("bestBid") or 0.0)
        liquidity_score = _liquidity_score(
            liquidity_num=liquidity_num,
            best_ask_depth=book_summary.ask_depth_at_best,
            cumulative_depth=book_summary.cumulative_ask_depth,
            spread=book_summary.spread,
        )
        volatility_score = _volatility_score(
            one_day_change=one_day_change,
            spread=book_summary.spread,
        )
        fee_bps = 0
        if market_payload.get("feesEnabled"):
            fee_bps = 25

        return MarketQuote(
            id=str(market_payload["id"]),
            event_id=event.id,
            event_title=event.title,
            event_slug=event.slug,
            question=market_payload.get("question") or "Untitled market",
            short_name=market_payload.get("groupItemTitle") or market_payload.get("question") or "Market",
            category=event.subcategory or event.category or "general",
            end_date=market_payload.get("endDate") or "",
            buy_yes_price=round(buy_yes, 4),
            sell_yes_price=round(sell_yes, 4),
            best_bid=round(book_summary.best_bid, 4),
            best_ask=round(book_summary.best_ask, 4),
            fee_bps=fee_bps,
            liquidity_score=liquidity_score,
            available_size=round(book_summary.cumulative_ask_depth, 2),
            freshness_seconds=book_summary.freshness_seconds,
            volatility_score=volatility_score,
            volume_num=volume_num,
            liquidity_num=liquidity_num,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            group_item_title=market_payload.get("groupItemTitle") or "",
            neg_risk=bool(market_payload.get("negRisk") or event.neg_risk),
            accepting_orders=bool(market_payload.get("acceptingOrders", True)),
            order_min_size=float(market_payload.get("orderMinSize") or 5.0),
            one_day_price_change=one_day_change,
            settled_yes=None,
        )

    @staticmethod
    def _derive_outcome_groups(events: list[MarketEvent]) -> list[OutcomeGroup]:
        groups: list[OutcomeGroup] = []
        for event in events:
            eligible_markets = [market for market in event.markets if market.neg_risk and market.accepting_orders]
            if len(eligible_markets) < 2:
                continue
            groups.append(
                OutcomeGroup(
                    id=f"event-{event.id}",
                    name=event.title,
                    event_id=event.id,
                    market_ids=[market.id for market in eligible_markets],
                    note="Live Polymarket neg-risk event. The YES outcomes are intended to partition the event into mutually exclusive buckets.",
                )
            )
        return groups

    @staticmethod
    def _derive_relations(events: list[MarketEvent]) -> list[MarketRelation]:
        relations: list[MarketRelation] = []
        for event in events:
            if event.neg_risk or len(event.markets) < 2:
                continue
            ordered = sorted(event.markets, key=lambda market: market.end_date or "")
            for earlier, later in zip(ordered, ordered[1:]):
                if later.end_date == earlier.end_date:
                    continue
                relations.append(
                    MarketRelation(
                        id=f"{event.id}:{earlier.id}:{later.id}",
                        name=f"{later.short_name} should not trade below {earlier.short_name}",
                        event_id=event.id,
                        broader_market_id=later.id,
                        narrower_market_id=earlier.id,
                        explanation=f"If '{earlier.question}' resolves YES by the earlier date, then '{later.question}' should also resolve YES by the later date.",
                    )
                )
        return relations


def _weighted_average_price(levels: list[OrderLevel], target_shares: float, *, side: str) -> float:
    if not levels:
        return 0.0
    remaining = max(target_shares, 1.0)
    notional = 0.0
    filled = 0.0
    for level in levels:
        take = min(level.size, remaining)
        notional += take * level.price
        filled += take
        remaining -= take
        if remaining <= 0:
            break
    if filled == 0:
        return 0.0
    average = notional / filled
    if side == "buy" and filled < target_shares:
        average += 0.01
    if side == "sell" and filled < target_shares:
        average -= 0.01
    return round(max(min(average, 1.0), 0.0), 4)


def _liquidity_score(
    *,
    liquidity_num: float,
    best_ask_depth: float,
    cumulative_depth: float,
    spread: float,
) -> float:
    liquidity_component = min(math.log10(max(liquidity_num, 1.0)) / 5.0, 1.0)
    depth_component = min(cumulative_depth / 200.0, 1.0) * 0.45 + min(best_ask_depth / 50.0, 1.0) * 0.15
    spread_penalty = min(spread / 0.08, 1.0) * 0.35
    return round(max(min(liquidity_component * 0.4 + depth_component - spread_penalty + 0.2, 0.99), 0.05), 2)


def _volatility_score(*, one_day_change: float, spread: float) -> float:
    return round(max(min(one_day_change * 2.5 + min(spread / 0.08, 1.0) * 0.35, 0.99), 0.01), 2)
