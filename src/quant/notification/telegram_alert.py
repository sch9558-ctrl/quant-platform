"""Telegram semi-automatic execution alert. No credentials => no send."""
from __future__ import annotations
import os
import requests

def format_signal(signal:dict)->str:
    return (
        f"🚨 [Quant Platform 정예 매매 시그널] {signal.get('date','')}\n"
        f"- 종목: {signal.get('company',signal.get('symbol'))} ({signal.get('symbol')}) | {signal.get('market','')}\n"
        f"- 액션: {signal.get('action','관망')}\n"
        f"- 진입 밴드: {signal.get('entry_band','—')}\n"
        f"- 목표가: {signal.get('target','—')}\n"
        f"- 손절가: {signal.get('stop','—')}\n"
        f"- 손익비: {signal.get('risk_reward','—')}\n"
        f"- 권장 비중: {signal.get('weight','—')}\n"
        f"- 근거: {signal.get('reason','정량 모델 검증 통과')}"
    )

def send_telegram(text:str,token:str|None=None,chat_id:str|None=None,timeout:int=10)->bool:
    token=token or os.getenv("TELEGRAM_BOT_TOKEN"); chat_id=chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:return False
    r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat_id,"text":text},timeout=timeout)
    r.raise_for_status(); return True
