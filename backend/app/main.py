from __future__ import annotations

import json
import logging
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import AuditEvent
from app.services.market_data import MarketDataUnavailableError, PolymarketDataProvider
from app.services.opportunities import Opportunity, OpportunityEngine, ScanResult
from app.services.paper import PaperTradingService
from app.services.risk import RiskManager


def configure_logging() -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.log_path, maxBytes=1_000_000, backupCount=2)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))

provider = PolymarketDataProvider()
risk_manager = RiskManager()
engine_service = OpportunityEngine(risk_manager=risk_manager)
paper_service = PaperTradingService(
    provider=provider,
    risk_manager=risk_manager,
)


def format_money(value: float) -> str:
    return f"${value:,.2f}"


def format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_cents(value: float) -> str:
    return f"{value * 100:.1f}c"


templates.env.filters["money"] = format_money
templates.env.filters["pct"] = format_percent
templates.env.filters["cents"] = format_cents


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        risk_manager.get_or_create_settings(db)
    logger.info("Application started")


def _dashboard_data(db: Session) -> dict:
    settings_row = risk_manager.get_or_create_settings(db)
    stats = risk_manager.compute_paper_stats(db)
    live_gate = risk_manager.evaluate_live_eligibility(settings_row, stats)
    recent_trades = paper_service.list_recent_trades(db)
    try:
        current_snapshot = provider.load_current_snapshot()
        scan = engine_service.scan(snapshot=current_snapshot, db=db)
        top = scan.opportunities[0] if scan.opportunities else None
        headline = (
            "No good trade right now."
            if not top
            else f"Best current setup: {top.name}. {top.recommended_action} first."
        )
        data_error = None
    except MarketDataUnavailableError as exc:
        scan = ScanResult(snapshot_id="unavailable", as_of="", markets_scanned=0, opportunities=[], rejected=[])
        headline = "Live Polymarket data is temporarily unavailable."
        data_error = str(exc)
    return {
        "scan": scan,
        "settings": settings_row,
        "stats": stats,
        "live_gate": live_gate,
        "recent_trades": recent_trades,
        "headline": headline,
        "data_error": data_error,
    }


def _find_opportunity(db: Session, opportunity_id: str) -> Opportunity:
    try:
        current_snapshot = provider.load_current_snapshot(force_refresh=True)
    except MarketDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    scan = engine_service.scan(snapshot=current_snapshot, db=db)
    for opportunity in scan.opportunities:
        if opportunity.id == opportunity_id:
            return opportunity
    raise HTTPException(status_code=404, detail="Opportunity not found")


def _audit(db: Session, event_type: str, payload: dict) -> None:
    db.add(AuditEvent(event_type=event_type, details_json=json.dumps(payload, ensure_ascii=True)))
    db.commit()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _dashboard_data(db)
    context.update(
        {
            "request": request,
            "page_title": "Dashboard",
            "message": request.query_params.get("message"),
        }
    )
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/opportunities/{opportunity_id}", response_class=HTMLResponse)
def opportunity_detail(
    request: Request,
    opportunity_id: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    opportunity = _find_opportunity(db, opportunity_id)
    context = _dashboard_data(db)
    context.update(
        {
            "request": request,
            "page_title": "Opportunity",
            "opportunity": opportunity,
            "message": request.query_params.get("message"),
        }
    )
    return templates.TemplateResponse("opportunity.html", context)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _dashboard_data(db)
    context.update(
        {
            "request": request,
            "page_title": "Settings",
            "message": request.query_params.get("message"),
        }
    )
    return templates.TemplateResponse("settings.html", context)


@app.post("/opportunities/{opportunity_id}/simulate")
def simulate_trade(opportunity_id: str, db: Session = Depends(get_db)) -> RedirectResponse:
    opportunity = _find_opportunity(db, opportunity_id)
    paper_service.create_manual_trade(db, opportunity)
    message = quote(f"Added {opportunity.name} to paper trading.")
    return RedirectResponse(url=f"/?message={message}", status_code=303)


@app.post("/settings")
def update_settings(
    paper_bankroll: float = Form(...),
    max_trade_risk_pct: float = Form(...),
    daily_loss_cap: float = Form(...),
    per_market_loss_cap: float = Form(...),
    consecutive_loss_limit: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings_row = risk_manager.get_or_create_settings(db)
    settings_row.paper_bankroll = max(paper_bankroll, 50.0)
    settings_row.max_trade_risk_pct = min(max(max_trade_risk_pct, 0.01), 0.1)
    settings_row.daily_loss_cap = max(daily_loss_cap, 5.0)
    settings_row.per_market_loss_cap = max(per_market_loss_cap, 2.0)
    settings_row.consecutive_loss_limit = min(max(consecutive_loss_limit, 1), 5)
    db.commit()
    _audit(
        db,
        "settings_updated",
        {
            "paper_bankroll": settings_row.paper_bankroll,
            "max_trade_risk_pct": settings_row.max_trade_risk_pct,
        },
    )
    return RedirectResponse(url="/settings?message=Risk%20settings%20saved.", status_code=303)


@app.post("/paper/refresh")
def refresh_paper_trades(db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        summary = paper_service.refresh_trade_statuses(db)
    except MarketDataUnavailableError as exc:
        message = quote(str(exc))
        return RedirectResponse(url=f"/settings?message={message}", status_code=303)
    message = quote(
        f"Checked {summary['updated']} live paper trades. Resolved {summary['resolved']} of them."
    )
    return RedirectResponse(url=f"/settings?message={message}", status_code=303)


@app.post("/live-mode/toggle")
def toggle_live_mode(enable_live: bool = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    settings_row = risk_manager.get_or_create_settings(db)
    stats = risk_manager.compute_paper_stats(db)
    live_gate = risk_manager.evaluate_live_eligibility(settings_row, stats)
    if enable_live and not live_gate.allowed:
        return RedirectResponse(
            url="/settings?message=Live%20mode%20is%20still%20locked%20because%20paper%20results%20do%20not%20meet%20the%20gate.",
            status_code=303,
        )

    settings_row.live_mode_enabled = enable_live
    db.commit()
    _audit(db, "live_mode_toggled", {"enabled": enable_live})
    label = "enabled" if enable_live else "disabled"
    return RedirectResponse(url=f"/settings?message=Live%20mode%20{label}.", status_code=303)


@app.get("/api/dashboard")
def dashboard_api(db: Session = Depends(get_db)) -> JSONResponse:
    payload = _dashboard_data(db)
    return JSONResponse(
        {
            "headline": payload["headline"],
            "data_error": payload["data_error"],
            "scan": {
                "snapshot_id": payload["scan"].snapshot_id,
                "as_of": payload["scan"].as_of,
                "markets_scanned": payload["scan"].markets_scanned,
                "opportunities": [item.to_dict() for item in payload["scan"].opportunities],
                "rejected": [asdict(item) for item in payload["scan"].rejected],
            },
            "stats": asdict(payload["stats"]),
            "live_gate": asdict(payload["live_gate"]),
        }
    )


@app.get("/api/opportunities/{opportunity_id}")
def opportunity_api(opportunity_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    opportunity = _find_opportunity(db, opportunity_id)
    return JSONResponse(opportunity.to_dict())


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
