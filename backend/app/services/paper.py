from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, PaperTrade
from app.services.market_data import MarketSnapshot, SampleMarketDataProvider
from app.services.opportunities import Opportunity, OpportunityEngine
from app.services.risk import RiskManager


class PaperTradingService:
    def __init__(
        self,
        provider: SampleMarketDataProvider,
        engine: OpportunityEngine,
        risk_manager: RiskManager,
    ) -> None:
        self.provider = provider
        self.engine = engine
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

    def run_replay(self, db: Session) -> dict[str, float | int]:
        history = self.provider.load_historical_snapshots()
        created = 0
        skipped = 0
        for snapshot in history:
            scan = self.engine.scan(snapshot=snapshot, db=db)
            for opportunity in scan.opportunities:
                if opportunity.recommended_action == "Watch":
                    skipped += 1
                    continue

                existing = db.scalar(
                    select(PaperTrade).where(
                        PaperTrade.opportunity_id == opportunity.id,
                        PaperTrade.snapshot_id == opportunity.snapshot_id,
                        PaperTrade.source == "replay",
                    )
                )
                if existing:
                    skipped += 1
                    continue

                realized_pnl, result_label = self._evaluate_replay_trade(snapshot, opportunity)
                trade = PaperTrade(
                    opportunity_id=opportunity.id,
                    snapshot_id=opportunity.snapshot_id,
                    source="replay",
                    opportunity_name=opportunity.name,
                    strategy_type=opportunity.strategy_type,
                    action_label=opportunity.recommended_action,
                    status="CLOSED",
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
                    notes=f"Replay generated from {snapshot.snapshot_id}",
                    current_price_mark=1.0 if realized_pnl >= 0 else 0.0,
                    realized_pnl=realized_pnl,
                    result_label=result_label,
                    closed_at=datetime.utcnow(),
                )
                db.add(trade)
                created += 1

        db.add(
            AuditEvent(
                event_type="replay_run",
                details_json=json.dumps(
                    {"created": created, "skipped": skipped},
                    ensure_ascii=True,
                ),
            )
        )
        db.commit()
        stats = self.risk_manager.compute_paper_stats(db)
        return {
            "created": created,
            "skipped": skipped,
            "closed_trades": stats.closed_trades,
            "total_pnl": stats.total_pnl,
            "win_rate": stats.win_rate,
        }

    def list_recent_trades(self, db: Session, limit: int = 8) -> list[PaperTrade]:
        return list(
            db.scalars(
                select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(limit)
            )
        )

    @staticmethod
    def _evaluate_replay_trade(snapshot: MarketSnapshot, opportunity: Opportunity) -> tuple[float, str]:
        if opportunity.strategy_type == "sum_to_one":
            payout_units = opportunity.max_suggested_size / opportunity.unit_cost_after_costs
            realized = round(payout_units - opportunity.max_suggested_size, 2)
            return realized, "Basket settled as expected"

        primary_market = snapshot.markets[opportunity.primary_market_id]
        payout_units = opportunity.max_suggested_size / opportunity.unit_cost_after_costs
        realized = round(
            payout_units * (1.0 if primary_market.settled_yes else 0.0) - opportunity.max_suggested_size,
            2,
        )
        result_label = "Broader market finished YES" if primary_market.settled_yes else "Broader market finished NO"
        return realized, result_label
