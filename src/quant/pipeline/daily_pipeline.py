"""Daily adaptive actionable-signal assembly.

This orchestration layer converts validated dashboard candidates and analyst
credibility metadata into execution guidance. It never submits live orders.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import math

import numpy as np
import pandas as pd

from quant.analytics.adaptive_optimizer import AdaptiveOptimizer
from quant.analytics.calibrator import TargetPriceCalibrator
from quant.analytics.performance_tracker import PerformanceTracker
from quant.analytics.risk_manager import TradeRiskManager
from quant.risk.watchdog import inspect_watchdog
from quant.trading.execution_scheduler import build_execution_schedule


ACTION_KO={
    "BUY":"적극 진입 (High Conviction)",
    "HOLD":"관망 (Wait)",
    "SELL":"분할 매도/익절",
    "STOP_LOSS":"손절",
}


def _recent_system_stats(rows, now=None, days=90):
    if not rows:
        return {"hit_rate":None,"average_realized_rr":None,"n_resolved":0}
    end=pd.Timestamp(now or pd.Timestamp.now(tz="UTC"))
    end=end.tz_localize(None) if end.tzinfo else end
    start=end-pd.Timedelta(days=days)
    selected=[]
    for row in rows:
        ts=pd.Timestamp(row.generated_at)
        ts=ts.tz_localize(None) if ts.tzinfo else ts
        if ts>=start and row.outcome in {"TARGET_REACHED","STOPPED_OUT","EXPIRED"}:
            selected.append(row)
    if not selected:
        return {"hit_rate":None,"average_realized_rr":None,"n_resolved":0}
    hit=float(np.mean([r.outcome=="TARGET_REACHED" for r in selected]))
    rrs=[r.realized_risk_reward for r in selected if r.realized_risk_reward is not None]
    return {"hit_rate":hit,"average_realized_rr":float(np.mean(rrs)) if rrs else None,"n_resolved":len(selected)}


def _bias_from_events(events):
    vals=[]
    for e in events or []:
        d=e.get("disparity_pct")
        if d is not None and e.get("matured", True):
            vals.append(float(d)/100.0)
    return float(np.mean(vals)) if vals else 0.0


def _regime_factor(section):
    regime=(section or {}).get("regime") or {}
    text=" ".join(str(regime.get(k,"")) for k in ("summary","trend_regime","volatility_regime","risk_regime")).lower()
    if any(x in text for x in ("risk_off","bear","high_vol","위험","약세")): return 0.90
    if any(x in text for x in ("bull","trend_up","risk_on","강세")): return 1.03
    return 1.0


def _price_frame(candidate):
    rows=candidate.get("price_history") or []
    if not rows:
        return None
    df=pd.DataFrame(rows)
    if "date" not in df or "close" not in df:return None
    df["date"]=pd.to_datetime(df["date"])
    df=df.set_index("date").sort_index()
    close=pd.to_numeric(df["close"],errors="coerce")
    # Candidate payload contains close-only compact history. Use gap-based true
    # range proxy for sizing; the output explicitly labels it as a proxy.
    return pd.DataFrame({"high":close,"low":close,"close":close},index=df.index)


def _confidence_interval(calibrated_target, events, z=1.44):
    errs=[float(e["disparity_pct"])/100 for e in (events or []) if e.get("disparity_pct") is not None]
    if len(errs)<3:return (None,None)
    sigma=float(np.std(errs,ddof=1))
    return (calibrated_target*(1-z*sigma),calibrated_target*(1+z*sigma))


def build_actionable_signals(dashboard:dict,consensus:dict|None,portfolio_values:dict|None=None,
                             predictions_path:str|Path="data/db/predictions_log.jsonl"):
    portfolio_values=portfolio_values or {"korea":10_000_000.0,"us":10_000.0}
    consensus=consensus or {}
    cmap=consensus.get("by_symbol") or {}
    tracker=PerformanceTracker(predictions_path)
    history=tracker.load()
    adaptive=AdaptiveOptimizer().optimize_alpha(history,previous_alpha=0.0)
    stats=_recent_system_stats(history)
    calibrator=TargetPriceCalibrator()
    risk=TradeRiskManager(account_risk_pct=0.01,max_position_pct=0.10,atr_multiple=2.0)
    signals=[]

    for market in ("korea","us"):
        section=(dashboard.get("markets") or {}).get(market) or {}
        if section.get("blocked"):
            continue
        regime_factor=_regime_factor(section)
        for c in section.get("candidates") or []:
            price=float(c.get("price") or 0)
            if price<=0:continue
            key=f"{market}:{c.get('symbol')}"
            meta=cmap.get(key) or {}
            plan=c.get("trade_plan") or {}
            raw_target=float(meta.get("target_price_mean") or plan.get("target_2") or price)
            bias=_bias_from_events(meta.get("events"))
            effective_bias=max(0.0,bias+adaptive.alpha)
            calibrated=calibrator.calibrate_target_price(raw_target,effective_bias,regime_factor)
            support=float(plan.get("stop_loss") or price*0.95)
            trade=calibrator.generate_trade_signal(price,calibrated,support)

            df=_price_frame(c)
            if df is not None and len(df)>=2:
                try:
                    rp=risk.build_plan(df,float(portfolio_values.get(market,0)),entry_price=price)
                    stop=max(float(rp.stop_price),support)
                    qty=rp.quantity
                    weight=rp.portfolio_weight
                    atr=rp.atr14
                except Exception:
                    stop=support; qty=0; weight=0.0; atr=None
            else:
                stop=support; qty=0; weight=0.0; atr=None

            rr=(calibrated-price)/max(price-stop,1e-9)
            ci_low,ci_high=_confidence_interval(calibrated,meta.get("events"))
            entry_low=float(plan.get("entry_low") or price*0.98)
            entry_high=float(plan.get("entry_high") or price)
            schedule=[asdict(x) for x in build_execution_schedule(qty,entry_low,entry_high)] if qty>0 else []
            target_gap=meta.get("target_gap_pct")
            watchdog=inspect_watchdog(None,{},[target_gap] if target_gap is not None else [])
            decision=trade.decision
            if watchdog.safe_mode and decision=="BUY": decision="HOLD"
            credibility=meta.get("credibility") or {}
            conviction="High" if decision=="BUY" and float(credibility.get("credibility_score") or 50)>=70 and rr>=2.0 else "Moderate" if decision=="BUY" else "Wait"
            signals.append({
                "market":market,
                "symbol":str(c.get("symbol")),
                "company":c.get("company"),
                "as_of":section.get("as_of"),
                "current_price":price,
                "decision":decision,
                "decision_ko":ACTION_KO.get(decision,decision),
                "conviction":conviction,
                "entry_low":entry_low,
                "entry_high":entry_high,
                "raw_consensus_target":raw_target,
                "analyst_bias":round(bias,6),
                "adaptive_alpha":round(adaptive.alpha,6),
                "market_regime_factor":regime_factor,
                "calibrated_target":round(calibrated,4),
                "target_ci_85_low":round(ci_low,4) if ci_low is not None else None,
                "target_ci_85_high":round(ci_high,4) if ci_high is not None else None,
                "stop_loss":round(stop,4),
                "atr14_or_proxy":round(atr,4) if atr is not None else None,
                "risk_reward":round(float(rr),3),
                "recommended_quantity":int(qty),
                "recommended_weight":round(float(weight),4),
                "max_weight":0.10,
                "risk_cleared":not watchdog.safe_mode,
                "watchdog_issues":list(watchdog.issues),
                "execution_schedule":schedule,
                "analyst_credibility":credibility,
                "system_90d":stats,
            })
    signals.sort(key=lambda x:(x["decision"]!="BUY",-x["risk_reward"],-x["recommended_weight"]))
    return {
        "schema_version":1,
        "generated_at":pd.Timestamp.now(tz="UTC").isoformat(),
        "adaptive_state":{"alpha":adaptive.alpha,"rmse":adaptive.rmse,"n_obs":adaptive.n_obs},
        "system_90d":stats,
        "signals":signals,
        "note_ko":"실거래 주문이 아닌 연구·모의집행 가이드입니다. LIVE_TRADING은 별도 승인 전까지 비활성화됩니다.",
    }


def write_actionable_signals(payload:dict,path="site/data/actionable_signals.json"):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return p
