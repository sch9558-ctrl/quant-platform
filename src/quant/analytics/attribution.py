"""Brinson-Fachler portfolio attribution."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import pandas as pd

@dataclass(frozen=True)
class AttributionResult:
    allocation: float
    selection: float
    interaction: float
    active_return: float
    by_sector: dict
    def to_dict(self):return asdict(self)

def brinson_fachler(portfolio_weights,benchmark_weights,portfolio_returns,benchmark_returns):
    pw=pd.Series(portfolio_weights,dtype=float);bw=pd.Series(benchmark_weights,dtype=float);pr=pd.Series(portfolio_returns,dtype=float);br=pd.Series(benchmark_returns,dtype=float)
    sectors=sorted(set(pw.index)|set(bw.index)|set(pr.index)|set(br.index))
    pw=pw.reindex(sectors).fillna(0);bw=bw.reindex(sectors).fillna(0);pr=pr.reindex(sectors).fillna(0);br=br.reindex(sectors).fillna(0)
    bench_total=float((bw*br).sum());alloc=(pw-bw)*(br-bench_total);select=bw*(pr-br);inter=(pw-bw)*(pr-br)
    rows={s:{"allocation":float(alloc[s]),"selection":float(select[s]),"interaction":float(inter[s])} for s in sectors}
    A=float(alloc.sum());S=float(select.sum());I=float(inter.sum());active=float((pw*pr).sum()-(bw*br).sum())
    return AttributionResult(A,S,I,active,rows)
