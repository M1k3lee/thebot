from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AppSettings, PaperTrade


@dataclass(slots=True)
class PaperStats:
    open_trades: int
    closed_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    expected_profit_total: float
    edge_capture_ratio: float
    consecutive_losses: int
    daily_realized_loss: float


@dataclass(slots=True)
class LiveEligibility:
    allowed: bool
    checks: list[dict[str, Any]]


class RiskManager:
    def get_or_create_settings(self, db: Session) -> AppSettings:
        existing = db.get(AppSettings, 1)
        if existing:
            return existing

        defaults = AppSettings(
            id=1,
            paper_bankroll=settings.default_paper_bankroll,
            max_trade_risk_pct=settings.default_max_trade_risk_pct,
            daily_loss_cap=settings.default_daily_loss_cap,
            per_market_loss_cap=settings.default_per_market_loss_cap,
            consecutive_loss_limit=settings.default_consecutive_loss_limit,
            live_mode_enabled=settings.default_live_mode,
        )
        db.add(defaults)
        db.commit()
        db.refresh(defaults)
        return defaults

    def compute_paper_stats(self, db: Session) -> PaperStats:
        trades = list(db.scalars(select(PaperTrade).order_by(PaperTrade.created_at.asc())))
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        closed_trades = [trade for trade in trades if trade.status == "CLOSED"]
        operational_closed = [trade for trade in closed_trades if trade.source != "replay"]
        wins = sum(1 for trade in closed_trades if (trade.realized_pnl or 0.0) > 0)
        losses = sum(1 for trade in closed_trades if (trade.realized_pnl or 0.0) < 0)
        closed_count = len(closed_trades)
        total_pnl = round(sum(trade.realized_pnl or 0.0 for trade in closed_trades), 2)
        expected_profit_total = round(sum(trade.expected_profit for trade in closed_trades), 2)
        edge_capture_ratio = round(
            (total_pnl / expected_profit_total) if expected_profit_total > 0 else 0.0,
            2,
        )
        consecutive_losses = 0
        for trade in reversed(operational_closed):
            if (trade.realized_pnl or 0.0) < 0:
                consecutive_losses += 1
                continue
            break

        today = datetime.utcnow().date()
        daily_realized_loss = round(
            sum(
                abs(min(trade.realized_pnl or 0.0, 0.0))
                for trade in operational_closed
                if trade.closed_at and trade.closed_at.date() == today
            ),
            2,
        )
        return PaperStats(
            open_trades=len(open_trades),
            closed_trades=closed_count,
            wins=wins,
            losses=losses,
            win_rate=round((wins / closed_count) if closed_count else 0.0, 2),
            total_pnl=total_pnl,
            expected_profit_total=expected_profit_total,
            edge_capture_ratio=edge_capture_ratio,
            consecutive_losses=consecutive_losses,
            daily_realized_loss=daily_realized_loss,
        )

    def evaluate_live_eligibility(self, settings_row: AppSettings, stats: PaperStats) -> LiveEligibility:
        checks = [
            {
                "label": f"At least {settings.live_min_closed_trades} closed paper trades",
                "passed": stats.closed_trades >= settings.live_min_closed_trades,
                "current": stats.closed_trades,
            },
            {
                "label": f"Win rate of at least {int(settings.live_min_win_rate * 100)}%",
                "passed": stats.win_rate >= settings.live_min_win_rate,
                "current": stats.win_rate,
            },
            {
                "label": "Non-negative total paper P&L",
                "passed": stats.total_pnl >= settings.live_min_total_pnl,
                "current": stats.total_pnl,
            },
            {
                "label": f"Edge capture ratio of at least {settings.live_min_edge_capture:.2f}",
                "passed": stats.edge_capture_ratio >= settings.live_min_edge_capture,
                "current": stats.edge_capture_ratio,
            },
            {
                "label": "No kill-switch condition triggered",
                "passed": stats.consecutive_losses < settings_row.consecutive_loss_limit
                and stats.daily_realized_loss < settings_row.daily_loss_cap,
                "current": {
                    "consecutive_losses": stats.consecutive_losses,
                    "daily_realized_loss": stats.daily_realized_loss,
                },
            },
        ]
        return LiveEligibility(
            allowed=all(check["passed"] for check in checks),
            checks=checks,
        )

    def suggest_max_stake(
        self,
        *,
        settings_row: AppSettings,
        bankroll: float,
        loss_ratio: float,
        liquidity_capacity: float,
        fill_probability: float,
    ) -> float:
        trade_budget = bankroll * settings_row.max_trade_risk_pct
        daily_bound = max(settings_row.daily_loss_cap, 1.0) / max(loss_ratio, 0.25)
        market_bound = max(settings_row.per_market_loss_cap, 1.0) / max(loss_ratio, 0.25)
        liquidity_bound = liquidity_capacity * fill_probability
        safe_stake = min(trade_budget, daily_bound, market_bound, liquidity_bound)
        return round(max(safe_stake, 0.0), 2)

    def determine_action(
        self,
        *,
        live_mode_enabled: bool,
        live_allowed: bool,
        quality_score: int,
        estimated_edge: float,
        fill_probability: float,
        volatility_score: float,
        freshness_seconds: int,
        consecutive_losses: int,
        daily_realized_loss: float,
        settings_row: AppSettings,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if estimated_edge < settings.min_edge_per_dollar:
            reasons.append("Edge is too small after costs.")
        if quality_score < 65:
            reasons.append("Overall setup quality is too low.")
        if fill_probability < settings.min_fill_probability:
            reasons.append("The trade may not fill cleanly.")
        if volatility_score > settings.max_safe_volatility:
            reasons.append("Market is moving too quickly.")
        if freshness_seconds > settings.max_freshness_seconds:
            reasons.append("Data is getting stale.")
        if consecutive_losses >= settings_row.consecutive_loss_limit:
            reasons.append("Kill switch is on after consecutive losses.")
        if daily_realized_loss >= settings_row.daily_loss_cap:
            reasons.append("Daily loss cap has been reached.")
        if reasons:
            return "Watch", reasons
        if not live_mode_enabled or not live_allowed or quality_score < 85 or fill_probability < 0.75:
            return "Simulate", ["Paper mode is safer until the signal proves itself."]
        return "Small Trade", ["Live mode is enabled and all risk checks passed."]
