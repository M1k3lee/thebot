from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.market_data import MarketQuote, MarketRelation, MarketSnapshot, OutcomeGroup
from app.services.risk import RiskManager


@dataclass(slots=True)
class RejectedSetup:
    name: str
    reason: str
    strategy_type: str


@dataclass(slots=True)
class Opportunity:
    id: str
    snapshot_id: str
    name: str
    strategy_type: str
    simple_explanation: str
    quality_score: int
    confidence_label: str
    estimated_edge_per_dollar: float
    unit_cost_after_costs: float
    expected_profit_on_suggested_size: float
    max_suggested_size: float
    worst_case_loss: float
    recommended_action: str
    action_reasons: list[str]
    why_it_may_work: str
    what_could_go_wrong: str
    why_not_certain: str
    if_market_moves_against_you: str
    fees_assumed: float
    slippage_assumed: float
    fill_probability: float
    liquidity_quality: str
    data_freshness: str
    freshness_seconds: int
    volatility_score: float
    markets: list[dict[str, Any]]
    primary_market_id: str
    advanced_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["estimated_edge_bps"] = round(self.estimated_edge_per_dollar * 100, 2)
        return data


@dataclass(slots=True)
class ScanResult:
    snapshot_id: str
    as_of: str
    markets_scanned: int
    opportunities: list[Opportunity]
    rejected: list[RejectedSetup]


class OpportunityEngine:
    def __init__(self, risk_manager: RiskManager) -> None:
        self.risk_manager = risk_manager

    def scan(self, snapshot: MarketSnapshot, db: Session) -> ScanResult:
        settings_row = self.risk_manager.get_or_create_settings(db)
        stats = self.risk_manager.compute_paper_stats(db)
        live_gate = self.risk_manager.evaluate_live_eligibility(settings_row, stats)
        opportunities: list[Opportunity] = []
        rejected: list[RejectedSetup] = []

        for group in snapshot.outcome_groups:
            opportunity, reason = self._evaluate_group(
                group=group,
                snapshot=snapshot,
                settings_row=settings_row,
                live_allowed=live_gate.allowed,
                consecutive_losses=stats.consecutive_losses,
                daily_realized_loss=stats.daily_realized_loss,
            )
            if opportunity:
                opportunities.append(opportunity)
            else:
                rejected.append(reason)

        for relation in snapshot.relations:
            opportunity, reason = self._evaluate_relation(
                relation=relation,
                snapshot=snapshot,
                settings_row=settings_row,
                live_allowed=live_gate.allowed,
                consecutive_losses=stats.consecutive_losses,
                daily_realized_loss=stats.daily_realized_loss,
            )
            if opportunity:
                opportunities.append(opportunity)
            else:
                rejected.append(reason)

        opportunities.sort(
            key=lambda item: (
                item.quality_score,
                item.estimated_edge_per_dollar,
                item.fill_probability,
            ),
            reverse=True,
        )
        return ScanResult(
            snapshot_id=snapshot.snapshot_id,
            as_of=snapshot.as_of,
            markets_scanned=len(snapshot.markets),
            opportunities=opportunities,
            rejected=rejected,
        )

    def _evaluate_group(
        self,
        *,
        group: OutcomeGroup,
        snapshot: MarketSnapshot,
        settings_row,
        live_allowed: bool,
        consecutive_losses: int,
        daily_realized_loss: float,
    ) -> tuple[Opportunity | None, RejectedSetup]:
        markets = [snapshot.markets[market_id] for market_id in group.market_ids]
        gross_cost = round(sum(market.buy_yes_price for market in markets), 4)
        fees = round(sum(market.buy_yes_price * market.fee_bps / 10000 for market in markets), 4)
        slippage = round(sum(max(market.spread / 2, 0.001) for market in markets), 4)
        unit_cost = round(gross_cost + fees + slippage, 4)
        edge = round(1.0 - unit_cost, 4)
        fill_probability = round(self._fill_probability(markets), 2)
        min_liquidity = min(market.liquidity_score for market in markets)
        max_freshness = max(market.freshness_seconds for market in markets)
        avg_volatility = sum(market.volatility_score for market in markets) / len(markets)
        quality_score = self._score_sum_to_one(
            edge=edge,
            min_liquidity=min_liquidity,
            fill_probability=fill_probability,
            freshness_seconds=max_freshness,
            volatility_score=avg_volatility,
        )

        reject_reason = self._validate_common(
            edge=edge,
            fill_probability=fill_probability,
            liquidity_score=min_liquidity,
            freshness_seconds=max_freshness,
            volatility_score=avg_volatility,
        )
        if reject_reason:
            return None, RejectedSetup(
                name=group.name,
                reason=reject_reason,
                strategy_type="sum_to_one",
            )

        loss_ratio = round(max(market.buy_yes_price for market in markets) / unit_cost, 2)
        max_stake = self.risk_manager.suggest_max_stake(
            settings_row=settings_row,
            bankroll=settings_row.paper_bankroll,
            loss_ratio=loss_ratio,
            liquidity_capacity=min(market.available_size for market in markets),
            fill_probability=fill_probability,
        )
        if max_stake <= 0:
            return None, RejectedSetup(
                name=group.name,
                reason="Risk caps leave no sensible size.",
                strategy_type="sum_to_one",
            )
        expected_profit = round((max_stake / unit_cost) * edge, 2)
        worst_case_loss = round(max_stake * loss_ratio, 2)
        action, action_reasons = self.risk_manager.determine_action(
            live_mode_enabled=settings_row.live_mode_enabled,
            live_allowed=live_allowed,
            quality_score=quality_score,
            estimated_edge=edge,
            fill_probability=fill_probability,
            volatility_score=avg_volatility,
            freshness_seconds=max_freshness,
            consecutive_losses=consecutive_losses,
            daily_realized_loss=daily_realized_loss,
            settings_row=settings_row,
        )
        cards = [
            {
                "label": market.short_name,
                "question": market.question,
                "buy_yes_price": market.buy_yes_price,
                "fee_bps": market.fee_bps,
                "liquidity_score": market.liquidity_score,
            }
            for market in markets
        ]
        return (
            Opportunity(
                id=f"{snapshot.snapshot_id}:sum:{group.id}",
                snapshot_id=snapshot.snapshot_id,
                name=f"{group.name} basket",
                strategy_type="sum_to_one",
                simple_explanation=f"Buying every outcome costs {gross_cost:.1%} before costs, so the whole basket still sits below 100%.",
                quality_score=quality_score,
                confidence_label=self._confidence_label(quality_score),
                estimated_edge_per_dollar=edge,
                unit_cost_after_costs=unit_cost,
                expected_profit_on_suggested_size=expected_profit,
                max_suggested_size=max_stake,
                worst_case_loss=worst_case_loss,
                recommended_action=action,
                action_reasons=action_reasons,
                why_it_may_work="Exactly one outcome can win here. If the full basket costs less than a full $1 payout after costs, the gap is a real cushion.",
                what_could_go_wrong="You may not get all legs filled at the same time. Thin liquidity can leave you with only part of the basket.",
                why_not_certain="Fees, slippage, and partial fills can erase a small edge even when the math looks clean.",
                if_market_moves_against_you="If one leg fills and the others disappear, treat it as a bad partial fill and stop rather than chase.",
                fees_assumed=fees,
                slippage_assumed=slippage,
                fill_probability=fill_probability,
                liquidity_quality=self._liquidity_label(min_liquidity),
                data_freshness=self._freshness_label(max_freshness),
                freshness_seconds=max_freshness,
                volatility_score=round(avg_volatility, 2),
                markets=cards,
                primary_market_id=markets[0].id,
                advanced_notes=[
                    group.note,
                    f"Unit cost after fees and slippage: {unit_cost:.4f}",
                    f"Expected edge per $1 payout: {edge:.4f}",
                ],
            ),
            RejectedSetup(name=group.name, reason="", strategy_type="sum_to_one"),
        )

    def _evaluate_relation(
        self,
        *,
        relation: MarketRelation,
        snapshot: MarketSnapshot,
        settings_row,
        live_allowed: bool,
        consecutive_losses: int,
        daily_realized_loss: float,
    ) -> tuple[Opportunity | None, RejectedSetup]:
        broader = snapshot.markets[relation.broader_market_id]
        narrower = snapshot.markets[relation.narrower_market_id]
        logic_gap = round(narrower.buy_yes_price - broader.buy_yes_price, 4)
        fees = round(broader.buy_yes_price * broader.fee_bps / 10000, 4)
        slippage = round(max(broader.spread / 2, 0.001), 4)
        unit_cost = round(broader.buy_yes_price + fees + slippage, 4)
        edge = round(logic_gap - fees - slippage, 4)
        fill_probability = round(self._fill_probability([broader]), 2)
        quality_score = self._score_relation(
            edge=edge,
            gap=logic_gap,
            liquidity=broader.liquidity_score,
            fill_probability=fill_probability,
            freshness_seconds=broader.freshness_seconds,
            volatility_score=broader.volatility_score,
        )

        reject_reason = self._validate_common(
            edge=edge,
            fill_probability=fill_probability,
            liquidity_score=broader.liquidity_score,
            freshness_seconds=broader.freshness_seconds,
            volatility_score=broader.volatility_score,
        )
        if not reject_reason and logic_gap <= 0:
            reject_reason = "No monotonic pricing gap remains."
        if reject_reason:
            return None, RejectedSetup(
                name=relation.name,
                reason=reject_reason,
                strategy_type="cross_market",
            )

        max_stake = self.risk_manager.suggest_max_stake(
            settings_row=settings_row,
            bankroll=settings_row.paper_bankroll,
            loss_ratio=1.0,
            liquidity_capacity=broader.available_size,
            fill_probability=fill_probability,
        )
        if max_stake <= 0:
            return None, RejectedSetup(
                name=relation.name,
                reason="Risk caps leave no sensible size.",
                strategy_type="cross_market",
            )
        expected_profit = round((max_stake / unit_cost) * edge, 2)
        action, action_reasons = self.risk_manager.determine_action(
            live_mode_enabled=settings_row.live_mode_enabled,
            live_allowed=live_allowed,
            quality_score=quality_score,
            estimated_edge=edge,
            fill_probability=fill_probability,
            volatility_score=broader.volatility_score,
            freshness_seconds=broader.freshness_seconds,
            consecutive_losses=consecutive_losses,
            daily_realized_loss=daily_realized_loss,
            settings_row=settings_row,
        )
        return (
            Opportunity(
                id=f"{snapshot.snapshot_id}:rel:{relation.id}",
                snapshot_id=snapshot.snapshot_id,
                name=relation.name,
                strategy_type="cross_market",
                simple_explanation=f"The broader market trades {logic_gap:.1%} below the narrower one even though it includes it.",
                quality_score=quality_score,
                confidence_label=self._confidence_label(quality_score),
                estimated_edge_per_dollar=edge,
                unit_cost_after_costs=unit_cost,
                expected_profit_on_suggested_size=expected_profit,
                max_suggested_size=max_stake,
                worst_case_loss=max_stake,
                recommended_action=action,
                action_reasons=action_reasons,
                why_it_may_work=relation.explanation,
                what_could_go_wrong="This is not a locked-in arbitrage by itself. The broader market can still finish NO and lose the full stake.",
                why_not_certain="A pricing inconsistency can persist for a long time, and the narrower market can be wrong too.",
                if_market_moves_against_you="If the price drops, stop at your size cap. Do not average down and do not increase risk.",
                fees_assumed=fees,
                slippage_assumed=slippage,
                fill_probability=fill_probability,
                liquidity_quality=self._liquidity_label(broader.liquidity_score),
                data_freshness=self._freshness_label(broader.freshness_seconds),
                freshness_seconds=broader.freshness_seconds,
                volatility_score=broader.volatility_score,
                markets=[
                    {
                        "label": broader.short_name,
                        "question": broader.question,
                        "buy_yes_price": broader.buy_yes_price,
                        "role": "Broader market to buy",
                    },
                    {
                        "label": narrower.short_name,
                        "question": narrower.question,
                        "buy_yes_price": narrower.buy_yes_price,
                        "role": "Narrower market used as the logic check",
                    },
                ],
                primary_market_id=broader.id,
                advanced_notes=[
                    relation.explanation,
                    f"Logic gap before costs: {logic_gap:.4f}",
                    f"Unit cost after fees and slippage: {unit_cost:.4f}",
                ],
            ),
            RejectedSetup(name=relation.name, reason="", strategy_type="cross_market"),
        )

    @staticmethod
    def _fill_probability(markets: list[MarketQuote]) -> float:
        liquidity = min(market.liquidity_score for market in markets)
        freshness_penalty = max(market.freshness_seconds for market in markets) / 300
        spread_penalty = sum(market.spread for market in markets) / max(len(markets), 1)
        base = 0.35 + liquidity * 0.5
        adjusted = base - min(freshness_penalty, 0.25) - min(spread_penalty * 2, 0.1)
        return max(min(adjusted, 0.95), 0.15)

    @staticmethod
    def _validate_common(
        *,
        edge: float,
        fill_probability: float,
        liquidity_score: float,
        freshness_seconds: int,
        volatility_score: float,
    ) -> str | None:
        if edge < settings.min_edge_per_dollar:
            return "Edge disappears after costs."
        if fill_probability < settings.min_fill_probability:
            return "Fill odds are too weak for a beginner-friendly setup."
        if liquidity_score < settings.min_liquidity_score:
            return "Liquidity is too thin."
        if freshness_seconds > settings.max_freshness_seconds:
            return "Market data is too stale."
        if volatility_score > settings.max_safe_volatility:
            return "Volatility is too high for a cautious small-capital strategy."
        return None

    @staticmethod
    def _score_sum_to_one(
        *,
        edge: float,
        min_liquidity: float,
        fill_probability: float,
        freshness_seconds: int,
        volatility_score: float,
    ) -> int:
        score = (
            min(max(edge / 0.05, 0.0), 1.0) * 40
            + min_liquidity * 20
            + fill_probability * 15
            + max(0.0, 1 - freshness_seconds / 240) * 10
            + max(0.0, 1 - volatility_score) * 10
            + 10
        )
        return max(min(round(score), 99), 0)

    @staticmethod
    def _score_relation(
        *,
        edge: float,
        gap: float,
        liquidity: float,
        fill_probability: float,
        freshness_seconds: int,
        volatility_score: float,
    ) -> int:
        score = (
            min(max(edge / 0.05, 0.0), 1.0) * 32
            + min(max(gap / 0.06, 0.0), 1.0) * 18
            + liquidity * 15
            + fill_probability * 10
            + max(0.0, 1 - freshness_seconds / 240) * 10
            + max(0.0, 1 - volatility_score) * 10
            + 5
        )
        return max(min(round(score), 99), 0)

    @staticmethod
    def _liquidity_label(score: float) -> str:
        if score >= 0.8:
            return "Strong"
        if score >= 0.65:
            return "Okay"
        return "Thin"

    @staticmethod
    def _freshness_label(seconds: int) -> str:
        if seconds < 30:
            return f"{seconds} seconds old"
        if seconds < 120:
            return f"{seconds // 10 * 10} seconds old"
        return f"{seconds // 60} minutes old"

    @staticmethod
    def _confidence_label(score: int) -> str:
        if score >= 85:
            return "High"
        if score >= 70:
            return "Moderate"
        return "Low"
