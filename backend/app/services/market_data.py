from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass(slots=True)
class MarketQuote:
    id: str
    question: str
    short_name: str
    buy_yes_price: float
    sell_yes_price: float
    fee_bps: int
    liquidity_score: float
    available_size: float
    freshness_seconds: int
    volatility_score: float
    category: str
    settled_yes: bool | None = None

    @property
    def spread(self) -> float:
        return max(self.buy_yes_price - self.sell_yes_price, 0.0)

    @property
    def midpoint(self) -> float:
        return round((self.buy_yes_price + self.sell_yes_price) / 2, 4)


@dataclass(slots=True)
class OutcomeGroup:
    id: str
    name: str
    market_ids: list[str]
    note: str


@dataclass(slots=True)
class MarketRelation:
    id: str
    name: str
    broader_market_id: str
    narrower_market_id: str
    explanation: str


@dataclass(slots=True)
class MarketSnapshot:
    snapshot_id: str
    as_of: str
    markets: dict[str, MarketQuote]
    outcome_groups: list[OutcomeGroup] = field(default_factory=list)
    relations: list[MarketRelation] = field(default_factory=list)


class SampleMarketDataProvider:
    """Reads local JSON fixtures so the app works offline and cheaply."""

    def __init__(
        self,
        current_snapshot_path: Path | None = None,
        historical_snapshots_path: Path | None = None,
    ) -> None:
        self.current_snapshot_path = current_snapshot_path or settings.current_snapshot_path
        self.historical_snapshots_path = historical_snapshots_path or settings.historical_snapshots_path

    def load_current_snapshot(self) -> MarketSnapshot:
        return self._parse_snapshot(self._load_json(self.current_snapshot_path))

    def load_historical_snapshots(self) -> list[MarketSnapshot]:
        data = self._load_json(self.historical_snapshots_path)
        return [self._parse_snapshot(snapshot) for snapshot in data["snapshots"]]

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _parse_snapshot(self, payload: dict[str, Any]) -> MarketSnapshot:
        markets = {
            item["id"]: MarketQuote(
                id=item["id"],
                question=item["question"],
                short_name=item["short_name"],
                buy_yes_price=float(item["buy_yes_price"]),
                sell_yes_price=float(item["sell_yes_price"]),
                fee_bps=int(item["fee_bps"]),
                liquidity_score=float(item["liquidity_score"]),
                available_size=float(item["available_size"]),
                freshness_seconds=int(item["freshness_seconds"]),
                volatility_score=float(item["volatility_score"]),
                category=item["category"],
                settled_yes=item.get("settled_yes"),
            )
            for item in payload["markets"]
        }
        outcome_groups = [
            OutcomeGroup(
                id=item["id"],
                name=item["name"],
                market_ids=list(item["market_ids"]),
                note=item["note"],
            )
            for item in payload.get("outcome_groups", [])
        ]
        relations = [
            MarketRelation(
                id=item["id"],
                name=item["name"],
                broader_market_id=item["broader_market_id"],
                narrower_market_id=item["narrower_market_id"],
                explanation=item["explanation"],
            )
            for item in payload.get("relations", [])
        ]
        return MarketSnapshot(
            snapshot_id=payload["snapshot_id"],
            as_of=payload["as_of"],
            markets=markets,
            outcome_groups=outcome_groups,
            relations=relations,
        )
