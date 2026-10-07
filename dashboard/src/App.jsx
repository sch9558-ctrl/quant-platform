import {useEffect,useMemo,useState} from 'react'
import ActionableTradeCard from './components/ActionableTradeCard'
import InstitutionalTerminal from './components/InstitutionalTerminal'
import './styles.css'

const MARKET={korea:'국내 증시',us:'미국 증시'}
const SOURCE_NAME={licensed_csv_archive:'보유·라이선스 아카이브',naver_finance:'네이버 증권 리서치',yahoo_finance:'Yahoo Finance',finnhub:'Finnhub'}
function koStatus(v){return ({PASS:'정상',FAIL:'실패',WARNING:'주의',SKIPPED:'미실행',FRESH:'최신',STALE:'지연',UNKNOWN:'확인중'})[v]||v||'—'}
function Status({d}){const o=d?.overview||{},q=Number(o.quality_quarantine_count||0);return <div className={'system-status '+(o.data_integrity==='PASS'?'ok':'bad')}><b>{o.data_integrity==='PASS'?(q>0?`데이터 검증 통과 · 격리 ${q}종목`:'데이터 검증 통과'):'데이터 검증 실패'}</b><span>기준일 {d?.as_of||'—'} · 투자준비 {o.investment_readiness||'—'}</span>{q>0&&<small>{o.quality_quarantine_note_ko}</small>}</div>}
function AnalystTable({consensus}){
 const rows=consensus?.institutions||[]
 return <section className="panel"><div className="section-title"><div><span className="eyebrow">REPORT TRACKER</span><h2>증권사·IB 신뢰도</h2></div><p>3개월 평가기간이 끝난 리포트만 미적중으로 확정하며, 표본이 적으면 등급을 ‘관찰중’으로 제한합니다.</p></div><div className="table-wrap"><table><thead><tr><th>기관</th><th>전체</th><th>평가가능</th><th>평가중</th><th>적중률</th><th>표본신뢰</th><th>신뢰도</th><th>등급</th></tr></thead><tbody>{rows.length?rows.slice(0,20).map((r,i)=><tr key={i}><td>{r.institution}</td><td>{r.n_reports}</td><td>{r.n_evaluable ?? 0}</td><td>{r.n_pending_target_reports ?? 0}</td><td>{r.hit_rate==null?'평가중':Math.round(r.hit_rate*100)+'%'}</td><td>{Math.round((r.sample_confidence||0)*100)}%</td><td>{r.credibility_score}</td><td><b>{r.tier}</b></td></tr>):<tr><td colSpan="8" className="muted">과거 리포트 메타데이터가 쌓이면 자동으로 순위가 표시됩니다.</td></tr>}</tbody></table></div></section>
}
function InstitutionalDiagnostics({data,market}){
 const p=data?.portfolio?.[market]||{}
 const strategies=data?.strategies?.[market]||[]
 const top=strategies[0]
 const method=(p.notes||[]).find(x=>String(x).startsWith('institutional allocator:'))||'기관형 포트폴리오 미사용'
 const methodKo=method.includes('black_litterman')?'Black-Litterman':method.includes('hrp')?'HRP':method.includes('legacy')?'기존 제약형':'확인 필요'
 const dsr=top?.deflated_sharpe_probability
 const cpcv=top?.cpcv_positive_sharpe_ratio
 const state=top?.approval_state
 const stateKo=state==='APPROVED'?'승인':state==='REJECTED'?'기각':state==='INSUFFICIENT_EVIDENCE'?'증거 부족(보류)':'—'
 const reasons=top?.approval_reasons||[]
 return <><section className="market-summary"><div><span>포트폴리오 엔진</span><b>{methodKo}</b></div><div><span>현금 비중</span><b>{p.cash_weight==null?'—':(Number(p.cash_weight)*100).toFixed(1)+'%'}</b></div><div><span>상위 전략 DSR</span><b>{dsr==null?'평가대기':(Number(dsr)*100).toFixed(1)+'%'}</b></div><div><span>CPCV 양(+) Sharpe</span><b>{cpcv==null?'평가대기':(Number(cpcv)*100).toFixed(1)+'%'}</b></div><div><span>전략 승인</span><b>{stateKo}</b></div></section>{reasons.length>0&&<section className="panel"><div className="section-title"><div><span className="eyebrow">STRATEGY VALIDATION</span><h2>전략 승인 근거</h2></div></div><ul className="reasons">{reasons.map((r,i)=><li key={i}>{r}</li>)}</ul></section>}</>
}
function PortfolioRiskSection({data,market}){
 const r=data?.portfolio_risk?.[market]||{}
 const stateKo=({NORMAL:'정상',SOFT_STOP:'소프트스톱',HARD_KILL_SWITCH:'하드 킬스위치',INSUFFICIENT_EVIDENCE:'증거 부족(보류)',DATA_VALIDATION_FAILED:'데이터 검증 실패'})[r.state]||r.state||'—'
 const pct=v=>v==null?'—':(Number(v)*100).toFixed(2)+'%'
 return <section className="panel"><div className="section-title"><div><span className="eyebrow">PORTFOLIO RISK GUARD</span><h2>포트폴리오 리스크</h2></div><p>운용 NAV와 검증 가격수익률이 없으면 임의값으로 통과시키지 않습니다.</p></div><div className="market-summary"><div><span>95% VaR(모수)</span><b>{pct(r.var95_parametric)}</b></div><div><span>95% VaR(역사적)</span><b>{pct(r.var95_historical)}</b></div><div><span>최대낙폭</span><b>{pct(r.max_drawdown)}</b></div><div><span>상태</span><b>{stateKo}</b></div></div>{(r.reasons||[]).length>0&&<ul className="reasons">{r.reasons.map((x,i)=><li key={i}>{x}</li>)}</ul>}</section>
}
function PaperVerification({data,market}){
 const p=data?.paper_trading?.[market]||{}
 const done=Number(p.sessions_completed||0),required=Number(p.sessions_required||250),pct=Number(p.progress_pct||0)
 return <section className="panel"><div className="section-title"><div><span className="eyebrow">LONG PRE-LIVE VERIFICATION</span><h2>실데이터 페이퍼 검증</h2></div><p>검증된 시장 세션만 누적하며 데이터 검증 실패일은 가산하지 않습니다.</p></div><div className="market-summary"><div><span>누적 거래일</span><b>{done}/{required}</b></div><div><span>시작일</span><b>{p.start_date||'아직 시작 전'}</b></div><div><span>진행률</span><b>{pct.toFixed(1)}%</b></div></div><p className="source-note">{p.validation_label_ko||'페이퍼 검증 기록 없음'}</p></section>
}
function SourceStatus({consensus}){
 const rows=consensus?.source_status||[]
 return <section className="panel source-panel"><div className="section-title"><div><span className="eyebrow">SOURCE COVERAGE</span><h2>리포트 수집 상태</h2></div><p>‘모든 보고서’ 커버리지를 가장해 표시하지 않고 실제 수집 소스와 건수를 공개합니다.</p></div><div className="source-grid">{rows.length?rows.map((r,i)=><div className={'source-card '+(r.ok?'ok':'bad')} key={i}><span>{SOURCE_NAME[r.source]||r.source}</span><b>{r.ok?'연결됨':'수집 실패'}</b><strong>{r.records||0}건</strong>{r.error&&<small>{r.error}</small>}</div>):<div className="muted">이번 실행의 소스 상태 정보가 없습니다.</div>}</div><p className="source-note">개별 애널리스트 이름·과거 전수 리포트는 무료 공개 소스만으로 완전하지 않을 수 있습니다. 보유/라이선스 CSV를 추가하면 동일 검증 엔진으로 합산합니다.</p></section>
}
export default function App(){
 const [data,setData]=useState(null),[consensus,setConsensus]=useState(null),[actionable,setActionable]=useState(null),[market,setMarket]=useState('korea'),[convertUsd,setConvertUsd]=useState(false),[error,setError]=useState('')
 useEffect(()=>{Promise.all([
  fetch('data/dashboard.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('dashboard.json '+r.status);return r.json()}),
  fetch('data/consensus_accuracy.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null),
  fetch('data/actionable_signals.json',{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)
 ]).then(([d,c,a])=>{setData(d);setConsensus(c);setActionable(a)}).catch(e=>setError(e.message))},[])
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
   <div className="disclaimer">모델·과거 데이터 기반 연구 정보이며 투자 자문이 아니고 투자 성과를 약속하지 않습니다. 데이터 검증 실패 시 후보를 표시하지 않습니다. 목표가·손절가는 조건부 연구 시나리오입니다.</div>
   <div className="market-toolbar"><nav className="market-tabs">{Object.entries(MARKET).map(([k,v])=><button key={k} className={market===k?'active':''} onClick={()=>setMarket(k)}>{v}</button>)}</nav>{market==='us'&&<div className="fx-toggle"><button disabled={!fxRate} className={convertUsd?'active':''} onClick={()=>fxRate&&setConvertUsd(v=>!v)}>{convertUsd?'원화 환산 ON':'USD 표시'}</button><span>{fxRate?('USD/KRW '+Number(fxRate).toLocaleString('ko-KR')+' · '+(fx?.quote_date||'')):'환율 미수집'}</span></div>}</div>
   {section?.blocked ? <section className="blocked"><h2>⛔ {MARKET[market]} 데이터 검증 실패</h2><p>{section.block_reason}</p><p>검증되지 않은 전일 후보를 오늘 후보처럼 재사용하지 않습니다.</p></section> :
   <><section className="market-summary"><div><span>시장 국면</span><b>{section?.regime?.summary||'—'}</b></div><div><span>분석 유니버스</span><b>{section?.universe_size||0}종목</b></div><div><span>오늘 후보</span><b>{cards.length}종목</b></div><div><span>품질 격리</span><b>{section?.quality_quarantine?.count||0}종목</b></div><div><span>데이터 상태</span><b>{koStatus(data?.data_quality?.[market]?.overall_status)}</b></div></section>{(section?.quality_quarantine?.count||0)>0&&<section className="panel notes"><h2>품질 격리 내역</h2><p><b>데이터 누락으로 제외된 종목: {section.quality_quarantine.count}개</b></p><p>종목: {(section.quality_quarantine.symbols||[]).join(', ')}</p>{section.quality_quarantine.explanation_ko&&<p>{section.quality_quarantine.explanation_ko}</p>}{section.quality_quarantine.warning&&<p><b>⚠ {section.quality_quarantine.warning_ko}</b></p>}{(section.quality_quarantine.consecutive_alert_symbols||[]).length>0&&<p><b>연속 격리 점검 필요: {section.quality_quarantine.consecutive_alert_symbols.join(', ')}</b></p>}<p>격리 종목은 투자 후보·포트폴리오 계산에서 제외됩니다.</p></section>}<section className="cards">{cards.length?cards.map(c=><ActionableTradeCard key={c.symbol} candidate={c} market={market} consensus={cmap[market+':'+c.symbol]} fxRate={fxRate} convertUsd={convertUsd}/>):<div className="empty">조건을 통과한 후보가 없습니다.</div>}</section></>}
   <InstitutionalDiagnostics data={data} market={market}/>
   <PaperVerification data={data} market={market}/>
   <PortfolioRiskSection data={data} market={market}/>
   <InstitutionalTerminal signals={actionable?.signals||[]} market={market} fxRate={fxRate} convertUsd={convertUsd}/>
   <AnalystTable consensus={consensus}/>
   <SourceStatus consensus={consensus}/>
   <section className="panel notes"><h2>데이터·검증 상태</h2><p>국내: {koStatus(data?.data_quality?.korea?.overall_status)} / 미국: {koStatus(data?.data_quality?.us?.overall_status)}</p>{fx&&<p>환율: {fx.available?('USD/KRW '+Number(fx.rate).toLocaleString('ko-KR')+' ('+(fx.quote_date||'기준일 미상')+')'):'미수집'} · {fx.note_ko}</p>}<p>{consensus?.source_notes_ko?.join(' · ')}</p></section>
 </main>
}
