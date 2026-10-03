"""Production actionable-signal assembly from validated dashboard research."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json

import pandas as pd

from quant.trading.execution_scheduler import build_execution_schedule


def _position_size(candidate: dict, capital: float) -> tuple[int, float]:
    plan = candidate.get("trade_plan") or {}
    entry = float(plan.get("entry_high") or candidate.get("price") or 0)
    stop = float(plan.get("stop_loss") or 0)
    if capital <= 0 or entry <= 0 or stop <= 0 or entry <= stop:
        return 0, 0.0
    by_risk = int((capital * 0.01) // max(entry - stop, 1e-9))
    by_weight = int((capital * 0.10) // entry)
    qty = max(0, min(by_risk, by_weight))
    return qty, (qty * entry / capital if capital else 0.0)


def build_actionable_signals(
    dashboard: dict,
    consensus: dict | None = None,
    portfolio_values: dict | None = None,
) -> dict:
    """Build the UI/execution contract from backend-approved research fields.

    No client-side risk recalculation is authoritative. The candidate's
    institutional_overlay controls whether a BUY can be emitted.
    """
    consensus = consensus or {}
    portfolio_values = portfolio_values or {"korea": 10_000_000.0, "us": 10_000.0}
    cmap = consensus.get("by_symbol") or {}
    signals = []

    for market in ("korea", "us"):
        section = (dashboard.get("markets") or {}).get(market) or {}
        if section.get("blocked"):
            continue
        for candidate in section.get("candidates") or []:
            overlay = candidate.get("institutional_overlay") or {}
            plan = candidate.get("trade_plan") or {}
            qty, weight = _position_size(candidate, float(portfolio_values.get(market, 0)))
            approved = bool(overlay.get("approved")) and bool(overlay.get("risk_cleared"))
            action = "BUY" if approved else "REVIEW"
            if qty <= 0 and action == "BUY":
                action = "REVIEW"
            schedule = [
                asdict(x)
                for x in build_execution_schedule(
                    qty,
                    float(plan.get("entry_low") or candidate.get("price") or 0),
                    side="BUY",
                )
            ] if qty > 0 else []
            key = f"{market}:{candidate.get('symbol')}"
            analyst = cmap.get(key) or {}
            signals.append({
                "market": market,
                "symbol": str(candidate.get("symbol")),
                "company": candidate.get("company"),
                "as_of": section.get("as_of"),
                "action": action,
                "action_ko": "매수 승인" if action == "BUY" else "검토 필요",
                "current_price": candidate.get("price"),
                "entry_low": plan.get("entry_low"),
                "entry_high": plan.get("entry_high"),
                "target_1": plan.get("target_1"),
                "target_2": plan.get("target_2"),
                "stop_loss": plan.get("stop_loss"),
                "risk_reward_1": plan.get("risk_reward_1"),
                "recommended_quantity": int(qty),
                "recommended_weight": round(float(weight), 6),
                "risk_cleared": bool(overlay.get("risk_cleared")),
                "external_checks_complete": bool(overlay.get("external_checks_complete")),
                "net_alpha_pct": overlay.get("net_alpha_pct"),
                "kelly_weight": overlay.get("position_weight"),
                "institutional_reasons": list(overlay.get("reasons") or []),
                "execution_schedule": schedule,
                "analyst_credibility": analyst.get("credibility"),
            })

    signals.sort(key=lambda x: (x["action"] != "BUY", -(x.get("net_alpha_pct") or -999)))
    return {
        "schema_version": 2,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "signals": signals,
        "note_ko": "실거래 주문이 아닌 검증·모의집행 가이드입니다. 외부 안전검사가 불완전하면 REVIEW로 차단됩니다.",
    }


def write_actionable_signals(payload: dict, path: str | Path = "site/data/actionable_signals.json") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p
