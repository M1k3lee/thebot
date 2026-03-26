from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class AppSettings(Base, TimestampMixin):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    paper_bankroll: Mapped[float] = mapped_column(Float, default=250.0, nullable=False)
    max_trade_risk_pct: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    daily_loss_cap: Mapped[float] = mapped_column(Float, default=18.0, nullable=False)
    per_market_loss_cap: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    consecutive_loss_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    live_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_mode_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    live_mode_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PaperTrade(Base, TimestampMixin):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    opportunity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(60), nullable=False)
    action_label: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False, index=True)
    stake_amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost_after_costs: Mapped[float] = mapped_column(Float, nullable=False)
    expected_edge_per_dollar: Mapped[float] = mapped_column(Float, nullable=False)
    expected_profit: Mapped[float] = mapped_column(Float, nullable=False)
    worst_case_loss: Mapped[float] = mapped_column(Float, nullable=False)
    fill_probability: Mapped[float] = mapped_column(Float, nullable=False)
    fees_assumed: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_assumed: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    markets_json: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    current_price_mark: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
