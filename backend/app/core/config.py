from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Plain Market"
    app_tagline: str = "Live Polymarket opportunities, filtered for clarity and risk."
    base_dir: Path = Path(__file__).resolve().parents[2]
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'plain_market.db'}"
    templates_dir: Path = Path(__file__).resolve().parents[1] / "templates"
    static_dir: Path = Path(__file__).resolve().parents[1] / "static"
    log_path: Path = Path(__file__).resolve().parents[2] / "logs" / "app.log"
    polymarket_gamma_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_base_url: str = "https://clob.polymarket.com"
    polymarket_events_limit: int = 100
    polymarket_scan_pages: int = 2
    polymarket_book_batch_size: int = 40
    polymarket_timeout_seconds: int = 20
    polymarket_cache_ttl_seconds: int = 25
    polymarket_target_shares: float = 25.0
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
    min_event_liquidity: float = 500.0
    min_market_liquidity: float = 250.0
    min_book_levels: int = 1


settings = Settings()
