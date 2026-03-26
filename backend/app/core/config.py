from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Plain Market"
    app_tagline: str = "Cautious prediction-market ideas, explained in plain English."
    base_dir: Path = Path(__file__).resolve().parents[2]
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'plain_market.db'}"
    current_snapshot_path: Path = Path(__file__).resolve().parents[1] / "data" / "current_snapshot.json"
    historical_snapshots_path: Path = Path(__file__).resolve().parents[1] / "data" / "historical_snapshots.json"
    templates_dir: Path = Path(__file__).resolve().parents[1] / "templates"
    static_dir: Path = Path(__file__).resolve().parents[1] / "static"
    log_path: Path = Path(__file__).resolve().parents[2] / "logs" / "app.log"
    default_paper_bankroll: float = 250.0
    default_max_trade_risk_pct: float = 0.05
    default_daily_loss_cap: float = 18.0
    default_per_market_loss_cap: float = 10.0
    default_consecutive_loss_limit: int = 3
    default_live_mode: bool = False
    min_edge_per_dollar: float = 0.012
    min_fill_probability: float = 0.55
    min_liquidity_score: float = 0.55
    max_freshness_seconds: int = 180
    max_safe_volatility: float = 0.65
    live_min_closed_trades: int = 5
    live_min_win_rate: float = 0.5
    live_min_total_pnl: float = 0.0
    live_min_edge_capture: float = 0.35


settings = Settings()
