import {useMemo,useState} from 'react'
import {formatPrice} from './ActionableTradeCard'

function executionRow(candidate, capital) {
  const p=candidate?.trade_plan||{}
  const entry=Number(p.entry_high ?? candidate?.price ?? 0)
  const stop=Number(p.stop_loss ?? 0)
  if(!entry || !stop || entry<=stop) return {...candidate, quantity:0, allocation:0}
  const riskBudget=capital*.01
  const byRisk=Math.floor(riskBudget/(entry-stop))
  const byWeight=Math.floor((capital*.10)/entry)
  const quantity=Math.max(0,Math.min(byRisk,byWeight))
  return {...candidate, quantity, allocation:quantity*entry/capital}
}

export default function InstitutionalTerminal({candidates=[],market,fxRate=null,convertUsd=false}) {
  const [capital,setCapital]=useState(market==='korea'?10_000_000:10_000)
  const rows=useMemo(()=>candidates.slice(0,8).map(c=>executionRow(c,Math.max(Number(capital)||0,1))),[candidates,capital])
  return <section className="panel">
    <div className="section-title"><div><span className="eyebrow">INSTITUTIONAL EXECUTION</span><h2>기관형 실행 콘솔</h2></div><p>1회 거래 위험 1%, 종목당 최대 10% 비중을 동시에 적용한 연구용 주문 수량입니다.</p></div>
    <div className="market-toolbar"><label>총 투자금&nbsp;<input aria-label="총 투자금" type="number" min="1" value={capital} onChange={e=>setCapital(e.target.value)}/></label></div>
    <div className="table-wrap"><table><thead><tr><th>종목</th><th>판정</th><th>지정 매수가</th><th>1차 목표</th><th>절대 손절</th><th>권장 수량</th><th>예상 비중</th></tr></thead>
    <tbody>{rows.length?rows.map(c=>{const p=c.trade_plan||{};return <tr key={c.symbol}><td><b>{c.company||c.symbol}</b><br/><span className="muted">{c.symbol}</span></td><td>{p.action_ko||'관망'}</td><td>{formatPrice(p.entry_high,market,fxRate,convertUsd)}</td><td>{formatPrice(p.target_1,market,fxRate,convertUsd)}</td><td>{formatPrice(p.stop_loss,market,fxRate,convertUsd)}</td><td><b>{c.quantity.toLocaleString()}주</b></td><td>{(c.allocation*100).toFixed(1)}%</td></tr>}):<tr><td colSpan="7" className="muted">실행 가능한 후보가 없습니다.</td></tr>}</tbody></table></div>
    <p className="source-note">실제 주문을 전송하지 않습니다. 데이터 품질·공시·유동성·리스크 게이트를 모두 통과한 뒤 별도 승인 절차에서만 집행해야 합니다.</p>
  </section>
