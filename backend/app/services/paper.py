from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, PaperTrade
from app.services.market_data import PolymarketDataProvider
from app.services.opportunities import Opportunity
from app.services.risk import RiskManager


class PaperTradingService:
    def __init__(
        self,
        provider: PolymarketDataProvider,
        risk_manager: RiskManager,
    ) -> None:
        self.provider = provider
        self.risk_manager = risk_manager

    def create_manual_trade(self, db: Session, opportunity: Opportunity) -> PaperTrade:
        existing = db.scalar(
            select(PaperTrade).where(
                PaperTrade.opportunity_id == opportunity.id,
                PaperTrade.snapshot_id == opportunity.snapshot_id,
                PaperTrade.status == "OPEN",
                PaperTrade.source == "manual",
            )
        )
        if existing:
            return existing

        trade = PaperTrade(
            opportunity_id=opportunity.id,
            snapshot_id=opportunity.snapshot_id,
            source="manual",
            opportunity_name=opportunity.name,
            strategy_type=opportunity.strategy_type,
            action_label="Simulate",
            status="OPEN",
            stake_amount=opportunity.max_suggested_size,
            unit_cost_after_costs=opportunity.unit_cost_after_costs,
            expected_edge_per_dollar=opportunity.estimated_edge_per_dollar,
            expected_profit=opportunity.expected_profit_on_suggested_size,
            worst_case_loss=opportunity.worst_case_loss,
            fill_probability=opportunity.fill_probability,
            fees_assumed=opportunity.fees_assumed,
            slippage_assumed=opportunity.slippage_assumed,
            quality_score=opportunity.quality_score,
            markets_json=json.dumps(opportunity.markets, ensure_ascii=True),
            notes=opportunity.why_it_may_work,
            current_price_mark=opportunity.unit_cost_after_costs,
        )
        db.add(trade)
        db.add(
            AuditEvent(
                event_type="paper_trade_created",
                details_json=json.dumps(
                    {
                        "opportunity_id": opportunity.id,
                        "stake_amount": opportunity.max_suggested_size,
                        "strategy_type": opportunity.strategy_type,
                    },
                    ensure_ascii=True,
                ),
            )
        )
        db.commit()
        db.refresh(trade)
        return trade

    def refresh_trade_statuses(self, db: Session) -> dict[str, int]:
        market_map = self.provider.load_market_map(include_closed=True)
        open_trades = list(db.scalars(select(PaperTrade).where(PaperTrade.status == "OPEN")))
        updated = 0
        resolved = 0

        for trade in open_trades:
            trade_markets = json.loads(trade.markets_json)
            market_ids = [str(item.get("id")) for item in trade_markets if item.get("id")]
            live_markets = [market_map.get(market_id) for market_id in market_ids if market_map.get(market_id)]
            if not live_markets:
                continue

            if trade.strategy_type == "sum_to_one":
                current_cost = round(sum(market.buy_yes_price for market in live_markets), 4)
                trade.current_price_mark = current_cost
                settled_yes_count = sum(1 for market in live_markets if market.settled_yes is True)
                settled_count = sum(1 for market in live_markets if market.settled_yes is not None)
                if settled_yes_count == 1 or (settled_count == len(live_markets) and settled_yes_count >= 1):
                    payout_units = trade.stake_amount / trade.unit_cost_after_costs
                    trade.realized_pnl = round(payout_units - trade.stake_amount, 2)
                    trade.result_label = "One basket outcome resolved YES"
                    trade.status = "CLOSED"
                    trade.closed_at = datetime.now(UTC).replace(tzinfo=None)
                    resolved += 1
            else:
                primary_market = live_markets[0]
                trade.current_price_mark = primary_market.buy_yes_price
                if primary_market.settled_yes is not None:
                    payout_units = trade.stake_amount / trade.unit_cost_after_costs
                    trade.realized_pnl = round(
                        payout_units * (1.0 if primary_market.settled_yes else 0.0) - trade.stake_amount,
                        2,
                    )
                    trade.result_label = (
                        "Primary market resolved YES" if primary_market.settled_yes else "Primary market resolved NO"
                    )
                    trade.status = "CLOSED"
                    trade.closed_at = datetime.now(UTC).replace(tzinfo=None)
                    resolved += 1
            updated += 1

        db.add(
            AuditEvent(
                event_type="paper_trade_refresh",
                details_json=json.dumps({"updated": updated, "resolved": resolved}, ensure_ascii=True),
            )
        )
        db.commit()
        return {"updated": updated, "resolved": resolved}

    def list_recent_trades(self, db: Session, limit: int = 8) -> list[PaperTrade]:
        return list(
            db.scalars(
                select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(limit)
            )
        )
