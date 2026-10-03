import {formatPrice} from './ActionableTradeCard'

export default function InstitutionalTerminal({signals=[],market,fxRate=null,convertUsd=false}) {
  const rows=(signals||[]).filter(s=>s.market===market).slice(0,8)
  return <section className="panel">
    <div className="section-title"><div><span className="eyebrow">INSTITUTIONAL EXECUTION</span><h2>기관형 실행 콘솔</h2></div><p>백엔드 통합 리스크 엔진의 승인·차단 결과만 표시합니다. 브라우저에서 위험 승인 여부를 다시 계산하지 않습니다.</p></div>
    <div className="table-wrap"><table><thead><tr><th>종목</th><th>최종 판정</th><th>지정 매수가</th><th>1차 목표</th><th>절대 손절</th><th>권장 수량</th><th>예상 비중</th><th>순 알파</th></tr></thead>
    <tbody>{rows.length?rows.map(s=><tr key={s.symbol}>
      <td><b>{s.company||s.symbol}</b><br/><span className="muted">{s.symbol}</span></td>
      <td><b>{s.action_ko||s.action}</b><br/><span className="muted">{s.risk_cleared?'Risk-Cleared':(s.external_checks_complete?'리스크 차단':'외부검사 미완료')}</span></td>
      <td>{formatPrice(s.entry_low,market,fxRate,convertUsd)} ~ {formatPrice(s.entry_high,market,fxRate,convertUsd)}</td>
      <td>{formatPrice(s.target_1,market,fxRate,convertUsd)}</td>
      <td>{formatPrice(s.stop_loss,market,fxRate,convertUsd)}</td>
      <td><b>{Number(s.recommended_quantity||0).toLocaleString()}주</b></td>
      <td>{((Number(s.recommended_weight)||0)*100).toFixed(1)}%</td>
      <td>{s.net_alpha_pct==null?'—':Number(s.net_alpha_pct).toFixed(2)+'%'}</td>
    </tr>):<tr><td colSpan="8" className="muted">백엔드에서 생성된 실행 신호가 없습니다.</td></tr>}</tbody></table></div>
    <p className="source-note">BUY는 backend institutional overlay가 승인한 경우에만 표시됩니다. 공시 등 외부 검사가 없으면 REVIEW로 fail-closed 처리합니다.</p>
  </section>
}
