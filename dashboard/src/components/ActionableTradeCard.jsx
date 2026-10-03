export function formatPrice(v, market) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return market === 'korea'
    ? Math.round(Number(v)).toLocaleString('ko-KR') + '원'
    : '$' + Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})
}
export default function ActionableTradeCard({candidate, market, consensus}) {
  const p=candidate.trade_plan || {}
  const credibility=consensus?.credibility
  const meanTarget=consensus?.target_price_mean
  return <article className="trade-card">
    <header className="trade-head">
      <div><div className="eyebrow">#{candidate.rank} {market==='korea'?'국내':'미국'} 후보</div><h2>{candidate.company || candidate.symbol}</h2><span className="ticker">{candidate.symbol}</span></div>
      <div className={'action action-'+(p.action||'HOLD').toLowerCase()}>{p.action_ko || '관망'}</div>
    </header>
    <div className="confidence"><span>모델 신뢰도</span><strong>{p.model_confidence ?? '—'}점</strong></div>
    <div className="levels">
      <div><span>적정 매수가</span><strong>{formatPrice(p.entry_low,market)} ~ {formatPrice(p.entry_high,market)}</strong></div>
      <div><span>1차 목표 · 2~4주</span><strong>{formatPrice(p.target_1,market)}</strong><small>+{p.target_1_upside_pct ?? '—'}%</small></div>
      <div><span>2차 목표 · 3~6개월</span><strong>{formatPrice(p.target_2,market)}</strong><small>+{p.target_2_upside_pct ?? '—'}%</small></div>
      <div className="danger"><span>손절 기준선</span><strong>{formatPrice(p.stop_loss,market)}</strong><small>{p.stop_loss_pct ?? '—'}%</small></div>
    </div>
    <div className="hold"><span>권장 보유기간</span><strong>{p.holding_period_ko || '—'}</strong></div>
    <ul className="reasons">{(p.reasons_ko||[]).slice(0,4).map((r,i)=><li key={i}>{r}</li>)}</ul>
    <section className="consensus-box">
      <h3>증권사/IB 리포트 검증</h3>
      {consensus ? <>
        <p>목표가 평균 <b>{formatPrice(meanTarget,market)}</b> · 분석 리포트 {consensus.report_count || 0}건</p>
        {credibility ? <p>3개월 적중률 <b>{Math.round((credibility.hit_rate||0)*100)}%</b> · 신뢰도 <b>{credibility.credibility_score}점 ({credibility.tier})</b></p> : <p className="muted">충분한 과거 검증 표본이 아직 없습니다.</p>}
      </> : <p className="muted">수집된 목표가/투자의견 메타데이터가 없습니다.</p>}
    </section>
    <p className="model-note">{p.note_ko || '모델 기반 연구 정보입니다.'}</p>
  </article>
}
