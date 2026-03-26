from __future__ import annotations

from app.services.market_data import SampleMarketDataProvider
from app.services.opportunities import OpportunityEngine
from app.services.paper import PaperTradingService
from app.services.risk import RiskManager


def build_services():
    risk_manager = RiskManager()
    provider = SampleMarketDataProvider()
    engine = OpportunityEngine(risk_manager=risk_manager)
    paper = PaperTradingService(provider=provider, engine=engine, risk_manager=risk_manager)
    return provider, engine, paper, risk_manager


def test_current_scan_finds_only_beginner_friendly_setups(db_session):
    provider, engine, _, risk_manager = build_services()
    risk_manager.get_or_create_settings(db_session)
    snapshot = provider.load_current_snapshot()

    scan = engine.scan(snapshot=snapshot, db=db_session)
    names = [item.name for item in scan.opportunities]
    rejected = {item.name: item.reason for item in scan.rejected}

    assert "Harbor City mayor race basket" in names
    assert "Fed cut by June should not be lower than Fed cut by May" in names
    assert "Metro budget finish" in rejected
    assert rejected["Metro budget finish"] == "Edge disappears after costs."
    assert all(item.recommended_action in {"Simulate", "Watch"} for item in scan.opportunities)


def test_replay_creates_closed_trades_and_positive_stats(db_session):
    _, _, paper, risk_manager = build_services()
    risk_manager.get_or_create_settings(db_session)

    summary = paper.run_replay(db_session)
    stats = risk_manager.compute_paper_stats(db_session)

    assert summary["created"] >= 5
    assert stats.closed_trades >= 5
    assert stats.win_rate >= 0.5
    assert stats.total_pnl > 0


def test_live_gate_unlocks_only_after_replay_validation(db_session):
    _, _, paper, risk_manager = build_services()
    settings_row = risk_manager.get_or_create_settings(db_session)

    before = risk_manager.evaluate_live_eligibility(settings_row, risk_manager.compute_paper_stats(db_session))
    assert before.allowed is False

    paper.run_replay(db_session)
    after = risk_manager.evaluate_live_eligibility(settings_row, risk_manager.compute_paper_stats(db_session))

    assert after.allowed is True
