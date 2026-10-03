import {useMemo,useState} from 'react'
import ExecutionCard from './ExecutionCard'

export default function InstitutionalTerminal({signals=[],market,fxRate=null,convertUsd=false}){
  const defaultCapital=market==='korea'?10000000:10000
  const [capital,setCapital]=useState(defaultCapital)
  const rows=useMemo(()=>signals.filter(s=>s.market===market).slice(0,8),[signals,market])
  return <section className="institutional-terminal panel">
    <div className="terminal-head"><div><span className="eyebrow">INSTITUTIONAL EXECUTION CONSOLE</span><h2>보정된 실전 매매 실행 시트</h2><p>애널리스트 편향·레짐·ATR/변동성 프록시·계좌 1% 위험 규칙을 합쳐 계산합니다. 실주문은 자동 실행하지 않습니다.</p></div>
      <label>가상 계좌금액<input type="number" min="0" value={capital} onChange={e=>setCapital(Number(e.target.value)||0)}/><small>{market==='korea'?'KRW':'USD'}</small></label>
    </div>
    {rows.length?<div className="execution-list">{rows.map(s=><ExecutionCard key={s.market+':'+s.symbol} signal={s} market={market} capital={capital} fxRate={fxRate} convertUsd={convertUsd}/>)}</div>:<div className="empty">현재 검증된 실행 시그널이 없습니다.</div>}
  </section>
}