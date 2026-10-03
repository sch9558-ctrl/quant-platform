export const US_COMPANY_KO = {
  AAPL:'애플', MSFT:'마이크로소프트', NVDA:'엔비디아', AMZN:'아마존',
  GOOGL:'알파벳 A', GOOG:'알파벳 C', META:'메타 플랫폼스', TSLA:'테슬라',
  AVGO:'브로드컴', BRK_B:'버크셔 해서웨이 B', JPM:'JP모건 체이스',
  V:'비자', MA:'마스터카드', WMT:'월마트', LLY:'일라이 릴리',
  ORCL:'오라클', NFLX:'넷플릭스', COST:'코스트코', AMD:'AMD',
  INTC:'인텔', CRM:'세일즈포스', ADBE:'어도비', QCOM:'퀄컴',
  MU:'마이크론 테크놀로지', PLTR:'팔란티어', UBER:'우버',
  SPY:'SPDR S&P 500 ETF', QQQ:'인베스코 QQQ ETF', VOO:'뱅가드 S&P 500 ETF',
  IVV:'아이셰어즈 코어 S&P 500 ETF', IWM:'아이셰어즈 러셀 2000 ETF',
  DIA:'SPDR 다우존스 ETF', VTI:'뱅가드 미국 전체시장 ETF',
}

export function companyDisplayName(candidate, market) {
  if (market !== 'us') return candidate.company || candidate.symbol
  const key=String(candidate.symbol||'').replace('.', '_')
  return US_COMPANY_KO[key] || candidate.company || candidate.symbol
}
