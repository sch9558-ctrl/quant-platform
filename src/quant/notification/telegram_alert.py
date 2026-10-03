"""Telegram alert formatting with fail-safe opt-in delivery."""
from __future__ import annotations
from dataclasses import dataclass
import os, requests

@dataclass(frozen=True)
class TelegramSendResult:
    sent: bool
    reason: str
    status_code: int | None = None

def _money(value, market):
    if value is None: return "—"
    return f"{float(value):,.0f}원" if market=="korea" else "$"+f"{float(value):,.2f}"

def format_trade_alert(signal):
    market=str(signal.get("market","us")).lower(); name=signal.get("company") or signal.get("name") or signal.get("symbol"); symbol=signal.get("symbol","—")
    return "\n".join([
        f"🚨 [Quant Platform 검증 매매 시그널] {signal.get('as_of','')}".rstrip(),
        f"- 종목: {name} ({symbol}) | {market.upper()}",
        f"- 액션: {signal.get('action_ko') or signal.get('action') or '관망'}"+(" (Risk-Cleared)" if signal.get("risk_cleared",False) else ""),
        f"- 진입 밴드: {_money(signal.get('entry_low'),market)} ~ {_money(signal.get('entry_high'),market)}",
        f"- 1차 목표가: {_money(signal.get('target_1'),market)}",
        f"- 손절가: {_money(signal.get('stop_loss'),market)}",
        f"- 손익비: {signal.get('risk_reward_1','—')} : 1",
        f"- 권장 비중: {signal.get('position_weight_pct','—')}%",
        f"- 근거: {signal.get('reason','모델·데이터 품질·리스크 필터 종합')}",
    ])

class TelegramAlert:
    def __init__(self, token=None, chat_id=None, timeout=10, session=None):
        self.token=token or os.getenv("TELEGRAM_BOT_TOKEN",""); self.chat_id=chat_id or os.getenv("TELEGRAM_CHAT_ID","")
        self.timeout=int(timeout); self.session=session or requests.Session()

    @property
    def configured(self): return bool(self.token and self.chat_id)

    def send_text(self,text):
        if not self.configured: return TelegramSendResult(False,"TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured")
        try:
            r=self.session.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id":self.chat_id,"text":text,"disable_web_page_preview":True},timeout=self.timeout)
            return TelegramSendResult(bool(r.ok),"sent" if r.ok else f"telegram HTTP {r.status_code}",r.status_code)
        except Exception as exc:
            return TelegramSendResult(False,f"telegram error: {type(exc).__name__}")

    def send_top_signals(self, signals, limit=5):
        return [self.send_text(format_trade_alert(dict(s))) for s in list(signals)[:max(0,int(limit))]]
