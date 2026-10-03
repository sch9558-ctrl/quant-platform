"""Composable institutional safety/alpha overlay for one candidate."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from quant.execution_model import ExecutionModel
from quant.risk.filing_filter import FilingRiskFilter
from quant.risk.market_traps import MarketTrapDetector
from quant.macro.cross_asset import evaluate_macro_gate
from quant.kelly import dynamic_kelly

@dataclass(frozen=True)
class InstitutionalOverlay:
    approved:bool
    action:str
    risk_cleared:bool
    net_alpha_pct:float
    position_weight:float
    reasons:tuple[str,...]
    def to_dict(self):return asdict(self)

def evaluate_candidate(candidate,*,filings=None,as_of=None,earnings_date=None,credit_balance_pct=None,open_price=None,previous_close=None,
                       usdkrw_1d_pct=None,sox_1d_pct=None,vix=None,us10y_change_bp=None,adv_notional=1e9,order_notional=1e7,
                       half_spread_bps=3,exchange_fee_bps=1,win_probability=.55,win_loss_ratio=2.0):
    market=str(candidate.get("market","us"));current=float(candidate.get("price") or candidate.get("current_price") or 0)
    target=float((candidate.get("trade_plan") or {}).get("target_1") or candidate.get("target_price") or current);gross=(target/current-1)*100 if current>0 else 0.
    filing=FilingRiskFilter().assess(filings or [],as_of=as_of);traps=MarketTrapDetector().assess(as_of=as_of,earnings_date=earnings_date,credit_balance_pct=credit_balance_pct,open_price=open_price,previous_close=previous_close)
    macro=evaluate_macro_gate(market=market,usdkrw_1d_pct=usdkrw_1d_pct,sox_1d_pct=sox_1d_pct,vix=vix,us10y_change_bp=us10y_change_bp)
    sigma=max(float(candidate.get("volatility") or .20)/252**.5,.001);cost=ExecutionModel().assess_signal(gross_alpha_pct=gross,order_notional=order_notional,adv_notional=adv_notional,sigma=sigma,half_spread_bps=half_spread_bps,exchange_fee_bps=exchange_fee_bps)
    risk_cleared=filing.risk_cleared and traps.risk_cleared and not macro.block_high_beta_growth
    kelly=dynamic_kelly(win_probability,win_loss_ratio,confidence=max(0,min(1,float(candidate.get("composite_score") or .5))));weight=kelly.portfolio_weight*macro.position_scale
    approved=risk_cleared and cost.accepted and weight>0;reasons=list(filing.matched_categories)+list(traps.reasons)+list(macro.reasons)
    if not cost.accepted:reasons.append("NET_ALPHA_BELOW_THRESHOLD")
    return InstitutionalOverlay(approved,"BUY" if approved else "PASS",risk_cleared,cost.net_alpha_pct,weight,tuple(reasons))
