import {formatPrice} from './ActionableTradeCard'

function pct(v,d=1){return v==null?'—':(Number(v)*100).toFixed(d)+'%'}
function rr(v){return v==null?'—':Number(v).toFixed(2)+' : 1'}

export default function ExecutionCard({signal,market,capital,fxRate=null,convertUsd=false}){
  const w=Math.max(0,Math.min(Number(signal.recommended_weight||0),Number(signal.max_weight||0.1)))
  const qty=signal.current_price>0?Math.floor(Number(capital||0)*w/Number(signal.current_price)):0
  const order=signal.decision==='BUY'?'BUY_LIMIT':signal.decision==='SELL'||signal.decision==='STOP_LOSS'?'SELL_LIMIT':'PASS'
  const sys=signal.system_90d||{}
  const cred=signal.analyst_credibility||{}
  return <article className="execution-card">
    <header><div><span className="eyebrow">EXECUTION SHEET</span><h3>{signal.company||signal.symbol} <small>{signal.symbol}</small></h3></div><b className={'exec-order '+order.toLowerCase()}>{order}</b></header>
    <div className="exec-decision"><strong>{signal.decision_ko}</strong><span>{signal.conviction==='High'?'High Conviction':signal.conviction==='Moderate'?'Moderate':'Wait'}</span></div>
    <div className="exec-grid">
      <div><span>현재가</span><b>{formatPrice(signal.current_price,market,fxRate,convertUsd)}</b></div>
      <div><span>매수 밴드</span><b>{formatPrice(signal.entry_low,market,fxRate,convertUsd)} ~ {formatPrice(signal.entry_high,market,fxRate,convertUsd)}</b></div>
      <div><span>보정 목표가</span><b>{formatPrice(signal.calibrated_target,market,fxRate,convertUsd)}</b><small>{signal.target_ci_85_low!=null?'85% 구간 '+formatPrice(signal.target_ci_85_low,market,fxRate,convertUsd)+' ~ '+formatPrice(signal.target_ci_85_high,market,fxRate,convertUsd):'표본 부족: 신뢰구간 계산 대기'}</small></div>
      <div className="danger"><span>절대 손절가</span><b>{formatPrice(signal.stop_loss,market,fxRate,convertUsd)}</b></div>
      <div><span>손익비</span><b>{rr(signal.risk_reward)}</b></div>
      <div><span>권장 비중</span><b>{pct(w)}</b><small>상한 {pct(signal.max_weight||.1)}</small></div>
      <div><span>권장 수량</span><b>{qty.toLocaleString('ko-KR')}주</b><small>입력 계좌금액 기준 재계산</small></div>
      <div><span>리스크 검증</span><b>{signal.risk_cleared?'통과':'안전모드'}</b></div>
    </div>
    <div className="calibration-strip">
      <span>원시 컨센서스 {formatPrice(signal.raw_consensus_target,market,fxRate,convertUsd)}</span>
      <span>애널리스트 편향 {pct(signal.analyst_bias)}</span>
      <span>적응 α {pct(signal.adaptive_alpha)}</span>
      <span>레짐계수 {Number(signal.market_regime_factor||1).toFixed(2)}</span>
      <span>리포트 신뢰도 {cred.credibility_score??'—'}점</span>
    </div>
    <div className="self-evolution"><b>자체 진화 지표</b><span>최근 90일 적중률 {sys.hit_rate==null?'표본 대기':pct(sys.hit_rate)} · 평균 실현 손익비 {sys.average_realized_rr==null?'표본 대기':Number(sys.average_realized_rr).toFixed(2)}</span></div>
  </article>
}