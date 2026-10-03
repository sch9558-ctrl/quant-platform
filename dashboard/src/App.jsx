import {useEffect,useMemo,useState} from 'react'
import ActionableTradeCard from './components/ActionableTradeCard'
import './styles.css'

const MARKET={korea:'국내 증시',us:'미국 증시'}
const SOURCE_NAME={licensed_csv_archive:'보유·라이선스 아카이브',naver_finance:'네이버 증권 리서치',yahoo_finance:'Yahoo Finance',finnhub:'Finnhub'}
function koStatus(v){return ({PASS:'정상',FAIL:'실패',WARNING:'주의',SKIPPED:'미실행',FRESH:'최신',STALE:'지연',UNKNOWN:'확인중'})[v]||v||'—'}
function Status({d}){const o=d?.overview||{};return <div className={'system-status '+(o.data_integrity==='PASS'?'ok':'bad')}><b>{o.data_integrity==='PASS'?'데이터 검증 통과':'데이터 검증 실패'}</b><span>기준일 {d?.as_of||'—'} · 투자준비 {o.investment_readiness||'—'}</span></div>}
function AnalystTable({consensus}){
 const rows=consensus?.institutions||[]
 return <section className="panel"><div className="section-title"><div><span className="eyebrow">REPORT TRACKER</span><h2>증권사·IB 신뢰도</h2></div><p>3개월 평가기간이 끝난 리포트만 미적중으로 확정하며, 표본이 적으면 등급을 ‘관찰중’으로 제한합니다.</p></div><div className="table-wrap"><table><thead><tr><th>기관</th><th>전체</th><th>평가가능</th><th>평가중</th><th>적중률</th><th>표본신뢰</th><th>신뢰도</th><th>등급</th></tr></thead><tbody>{rows.length?rows.slice(0,20).map((r,i)=><tr key={i}><td>{r.institution}</td><td>{r.n_reports}</td><td>{r.n_evaluable ?? 0}</td><td>{r.n_pending_target_reports ?? 0}</td><td>{r.hit_rate==null?'평가중':Math.round(r.hit_rate*100)+'%'}</td><td>{Math.round((r.sample_confidence||0)*100)}%</td><td>{r.credibility_score}</td><td><b>{r.tier}</b></td></tr>):<tr><td colSpan="8" className="muted">과거 리포트 메타데이터가 쌓이면 자동으로 순위가 표시됩니다.</td></tr>}</tbody></table></div></section>
}
function SourceStatus({consensus}){
 const rows=consensus?.source_status||[]
 return <section className="panel source-panel"><div className="section-title"><div><span className="eyebrow">SOURCE COVERAGE</span><h2>리포트 수집 상태</h2></div><p>‘모든 보고서’ 커버리지를 가장해 표시하지 않고 실제 수집 소스와 건수를 공개합니다.</p></div><div className="source-grid">{rows.length?rows.map((r,i)=><div className={'source-card '+(r.ok?'ok':'bad')} key={i}><span>{SOURCE_NAME[r.source]||r.source}</span><b>{r.ok?'연결됨':'수집 실패'}</b><strong>{r.records||0}건</strong>{r.error&&<small>{r.error}</small>}</div>):<div className="muted">이번 실행의 소스 상태 정보가 없습니다.</div>}</div><p className="source-note">개별 애널리스트 이름·과거 전수 리포트는 무료 공개 소스만으로 완전하지 않을 수 있습니다. 보유/라이선스 CSV를 추가하면 동일 검증 엔진으로 합산합니다.</p></section>
}
export default function App(){
 const [data,setData]=useState(null),[consensus,setConsensus]=useState(null),[market,setMarket]=useState('korea'),[convertUsd,setConvertUsd]=useState(false),[error,setError]=useState('')
 useEffect(()=>{Promise.all([fetch('data/dashboard.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('dashboard.json '+r.status);return r.json()}),fetch('data/consensus_accuracy.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)]).then(([d,c])=>{setData(d);setConsensus(c)}).catch(e=>setError(e.message))},[])
 const section=data?.markets?.[market]
 const candidates=section?.candidates||[]
 const cmap=consensus?.by_symbol||{}
 const cards=useMemo(()=>candidates.slice(0,12),[candidates])
 const fx=data?.fx
 const fxRate=fx?.available?fx.rate:null
 if(error)return <main className="shell"><div className="fatal">대시보드 데이터를 불러오지 못했습니다: {error}</div></main>
 if(!data)return <main className="shell"><div className="loading">퀀트 데이터를 불러오는 중…</div></main>
 return <main className="shell">
   <header className="hero"><div><span className="eyebrow">KOREA + US QUANT RESEARCH</span><h1>오늘의 퀀트 매매 가이드</h1><p>어떤 종목을 · 어느 가격에 진입하고 · 어느 조건에서 정리할지 한 화면에서 확인합니다.</p></div><Status d={data}/></header>
   <div className="disclaimer">모델·과거 데이터 기반 연구 정보이며 투자 자문이나 수익 보장이 아닙니다. 데이터 검증 실패 시 후보를 표시하지 않습니다. 목표가·손절가는 조건부 연구 시나리오입니다.</div>
   <div className="market-toolbar"><nav className="market-tabs">{Object.entries(MARKET).map(([k,v])=><button key={k} className={market===k?'active':''} onClick={()=>setMarket(k)}>{v}</button>)}</nav>{market==='us'&&<div className="fx-toggle"><button disabled={!fxRate} className={convertUsd?'active':''} onClick={()=>fxRate&&setConvertUsd(v=>!v)}>{convertUsd?'원화 환산 ON':'USD 표시'}</button><span>{fxRate?('USD/KRW '+Number(fxRate).toLocaleString('ko-KR')+' · '+(fx?.quote_date||'')):'환율 미수집'}</span></div>}</div>
   {section?.blocked ? <section className="blocked"><h2>⛔ {MARKET[market]} 데이터 검증 실패</h2><p>{section.block_reason}</p><p>검증되지 않은 전일 후보를 오늘 후보처럼 재사용하지 않습니다.</p></section> :
   <><section className="market-summary"><div><span>시장 국면</span><b>{section?.regime?.summary||'—'}</b></div><div><span>분석 유니버스</span><b>{section?.universe_size||0}종목</b></div><div><span>오늘 후보</span><b>{cards.length}종목</b></div><div><span>데이터 상태</span><b>{koStatus(data?.data_quality?.[market]?.overall_status)}</b></div></section><section className="cards">{cards.length?cards.map(c=><ActionableTradeCard key={c.symbol} candidate={c} market={market} consensus={cmap[market+':'+c.symbol]} fxRate={fxRate} convertUsd={convertUsd}/>):<div className="empty">조건을 통과한 후보가 없습니다.</div>}</section></>}
   <AnalystTable consensus={consensus}/>
   <SourceStatus consensus={consensus}/>
   <section className="panel notes"><h2>데이터·검증 상태</h2><p>국내: {koStatus(data?.data_quality?.korea?.overall_status)} / 미국: {koStatus(data?.data_quality?.us?.overall_status)}</p>{fx&&<p>환율: {fx.available?('USD/KRW '+Number(fx.rate).toLocaleString('ko-KR')+' ('+(fx.quote_date||'기준일 미상')+')'):'미수집'} · {fx.note_ko}</p>}<p>{consensus?.source_notes_ko?.join(' · ')}</p></section>
 </main>
}
