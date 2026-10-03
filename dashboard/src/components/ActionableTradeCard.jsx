export function formatPrice(v, market, fxRate=null, convertUsd=false) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  if (market === 'korea') return Math.round(Number(v)).toLocaleString('ko-KR') + '원'
  if (convertUsd && fxRate) return '≈ ' + Math.round(Number(v) * Number(fxRate)).toLocaleString('ko-KR') + '원'
  return '$' + Number(v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})
}
function pct(v, digits=1) {
  return v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(digits) + '%'
}
function hitRate(metric) {
  return metric?.hit_rate == null ? '평가중' : Math.round(metric.hit_rate * 100) + '%'
}
function EventTimeline({events=[], market, fxRate, convertUsd}) {
  const rows = events.slice(-4).reverse()
  if (!rows.length) return null
  return <div className="event-timeline">
    <div className="mini-title">최근 리포트 검증 타임라인</div>
    {rows.map((e,i)=><div className="event-row" key={i}>
      <span className={'event-dot ' + (e.hit===true?'hit':e.hit===false?'miss':'pending')}>{e.hit===true?'O':e.hit===false?'X':'…'}</span>
      <span>{e.published_at}</span>
      <b>{e.institution}</b>
      <span>{formatPrice(e.target_price, market, fxRate, convertUsd)}</span>
      <span className="muted">{e.hit==null?'평가기간 진행중':e.hit?'목표 도달':'기간 내 미도달'}</span>
    </div>)}
  </div>
}
export default function ActionableTradeCard({candidate, market, consensus, fxRate=null, convertUsd=false}) {
  const p = candidate.trade_plan || {}
  const credibility = consensus?.credibility
  const meanTarget = consensus?.target_price_mean
  const topSource = consensus?.top_credible_sources?.find(x=>x?.credibility?.n_evaluable>0) || consensus?.top_credible_sources?.[0]
  const gap = consensus?.target_gap_pct
  const gapClass = gap != null && gap >= 25 ? 'warn' : ''
  return <article className="trade-card">
    <header className="trade-head">
      <div><div className="eyebrow">#{candidate.rank} {market==='korea'?'국내':'미국'} 후보</div><h2>{candidate.company || candidate.symbol}</h2><span className="ticker">{candidate.symbol}</span></div>
      <div className={'action action-' + (p.action||'HOLD').toLowerCase()}>{p.action_ko || '관망'}</div>
    </header>
    <div className="snapshot-row">
      <div><span>현재 기준가</span><strong>{formatPrice(p.current_price ?? candidate.price, market, fxRate, convertUsd)}</strong></div>
      <div><span>모델 신뢰도</span><strong>{p.model_confidence ?? '—'}점</strong></div>
      <div><span>1차 손익비</span><strong>{p.risk_reward_1 ?? '—'} : 1</strong></div>
      <div><span>2차 손익비</span><strong>{p.risk_reward_2 ?? '—'} : 1</strong></div>
    </div>
    <div className="levels">
      <div><span>적정 매수가</span><strong>{formatPrice(p.entry_low, market, fxRate, convertUsd)} ~ {formatPrice(p.entry_high, market, fxRate, convertUsd)}</strong></div>
      <div><span>1차 목표 · 2~4주</span><strong>{formatPrice(p.target_1, market, fxRate, convertUsd)}</strong><small>+{p.target_1_upside_pct ?? '—'}%</small></div>
      <div><span>2차 목표 · 3~6개월</span><strong>{formatPrice(p.target_2, market, fxRate, convertUsd)}</strong><small>+{p.target_2_upside_pct ?? '—'}%</small></div>
      <div className="danger"><span>손절 기준선</span><strong>{formatPrice(p.stop_loss, market, fxRate, convertUsd)}</strong><small>{p.stop_loss_pct ?? '—'}%</small></div>
    </div>
    <div className="hold"><span>권장 보유기간</span><strong>{p.holding_period_ko || '—'}</strong></div>
    <div className="exit-rule"><b>매도/재평가 규칙</b><p>{p.exit_rule_ko || '목표가와 손절선을 기준으로 재평가합니다.'}</p><p>{p.review_rule_ko}</p></div>
    <ul className="reasons">{(p.reasons_ko||[]).slice(0,5).map((reason,i)=><li key={i}>{reason}</li>)}</ul>
    <section className="consensus-box">
      <div className="consensus-title"><h3>증권사/IB 리포트 검증</h3>{consensus?.target_gap_label_ko && <span className={'gap-badge ' + gapClass}>{consensus.target_gap_label_ko}</span>}</div>
      {consensus ? <>
        <p>목표가 평균 <b>{formatPrice(meanTarget, market, fxRate, convertUsd)}</b>{gap!=null && <> · 현재가 대비 <b className={gapClass}>{pct(gap)}</b></>} · 수집 {consensus.report_count || 0}건</p>
        {credibility ? <p>3개월 적중률 <b>{hitRate(credibility)}</b> · 성숙 표본 <b>{credibility.n_evaluable ?? 0}</b>건 · 평가중 목표 <b>{credibility.n_pending_target_reports ?? 0}</b>건 · 신뢰도 <b>{credibility.credibility_score}점 ({credibility.tier})</b></p> : <p className="muted">충분한 과거 검증 표본이 아직 없습니다.</p>}
        {topSource && <p>신뢰도 상위 기관 <b>{topSource.institution}</b> · {topSource.credibility.tier} · 평가표본 {topSource.credibility.n_evaluable ?? 0}건{topSource.target_price_mean!=null && <> · 해당 기관 평균 목표가 <b>{formatPrice(topSource.target_price_mean, market, fxRate, convertUsd)}</b></>}</p>}
        <EventTimeline events={consensus.events} market={market} fxRate={fxRate} convertUsd={convertUsd}/>
      </> : <p className="muted">수집된 목표가/투자의견 메타데이터가 없습니다.</p>}
    </section>
    <p className="model-note">{p.note_ko || '모델 기반 연구 정보입니다.'}</p>
  </article>
}
