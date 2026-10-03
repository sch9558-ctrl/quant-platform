import {useEffect,useMemo,useState} from 'react'
import ActionableTradeCard from './components/ActionableTradeCard'
import './styles.css'

const MARKET={korea:'국내 증시',us:'미국 증시'}
function Status({d}){const o=d?.overview||{};return <div className={'system-status '+(o.data_integrity==='PASS'?'ok':'bad')}><b>{o.data_integrity==='PASS'?'데이터 검증 통과':'데이터 검증 실패'}</b><span>기준일 {d?.as_of||'—'} · 투자준비 {o.investment_readiness||'—'}</span></div>}
function AnalystTable({consensus}){const rows=consensus?.institutions||[];return <section className="panel"><div className="section-title"><div><span className="eyebrow">REPORT TRACKER</span><h2>증권사·IB 신뢰도</h2></div><p>목표가가 실제 시장에서 얼마나 달성됐는지 3개월 기준으로 평가합니다.</p></div><div className="table-wrap"><table><thead><tr><th>기관</th><th>표본</th><th>적중률</th><th>신뢰도</th><th>등급</th></tr></thead><tbody>{rows.length?rows.slice(0,20).map((r,i)=><tr key={i}><td>{r.institution}</td><td>{r.n_reports}</td><td>{Math.round((r.hit_rate||0)*100)}%</td><td>{r.credibility_score}</td><td><b>{r.tier}</b></td></tr>):<tr><td colSpan="5" className="muted">과거 리포트 메타데이터가 쌓이면 자동으로 순위가 표시됩니다.</td></tr>}</tbody></table></div></section>}
export default function App(){
 const [data,setData]=useState(null),[consensus,setConsensus]=useState(null),[market,setMarket]=useState('korea'),[error,setError]=useState('')
 useEffect(()=>{Promise.all([fetch('data/dashboard.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('dashboard.json '+r.status);return r.json()}),fetch('data/consensus_accuracy.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)]).then(([d,c])=>{setData(d);setConsensus(c)}).catch(e=>setError(e.message))},[])
 const section=data?.markets?.[market]
 const candidates=section?.candidates||[]
 const cmap=consensus?.by_symbol||{}
 const cards=useMemo(()=>candidates.slice(0,12),[candidates])
 if(error)return <main className="shell"><div className="fatal">대시보드 데이터를 불러오지 못했습니다: {error}</div></main>
 if(!data)return <main className="shell"><div className="loading">퀀트 데이터를 불러오는 중…</div></main>
 return <main className="shell">
   <header className="hero"><div><span className="eyebrow">KOREA + US QUANT RESEARCH</span><h1>오늘의 퀀트 매매 가이드</h1><p>어떤 종목을 · 어느 가격에 · 언제 정리할지 한 화면에서 확인합니다.</p></div><Status d={data}/></header>
   <div className="disclaimer">모델·과거 데이터 기반 연구 정보이며 투자 자문이나 수익 보장이 아닙니다. 데이터 검증 실패 시 후보를 표시하지 않습니다.</div>
   <nav className="market-tabs">{Object.entries(MARKET).map(([k,v])=><button key={k} className={market===k?'active':''} onClick={()=>setMarket(k)}>{v}</button>)}</nav>
   {section?.blocked ? <section className="blocked"><h2>⛔ {MARKET[market]} 데이터 검증 실패</h2><p>{section.block_reason}</p><p>검증되지 않은 전일 후보를 오늘 후보처럼 재사용하지 않습니다.</p></section> :
   <><section className="market-summary"><div><span>시장 국면</span><b>{section?.regime?.summary||'—'}</b></div><div><span>분석 유니버스</span><b>{section?.universe_size||0}종목</b></div><div><span>오늘 후보</span><b>{cards.length}종목</b></div></section><section className="cards">{cards.length?cards.map(c=><ActionableTradeCard key={c.symbol} candidate={c} market={market} consensus={cmap[market+':'+c.symbol]}/>):<div className="empty">조건을 통과한 후보가 없습니다.</div>}</section></>}
   <AnalystTable consensus={consensus}/>
   <section className="panel notes"><h2>데이터·검증 상태</h2><p>국내: {data?.data_quality?.korea?.overall_status||'미수집'} / 미국: {data?.data_quality?.us?.overall_status||'미수집'}</p><p>{consensus?.source_notes_ko?.join(' · ')}</p></section>
 </main>
}
