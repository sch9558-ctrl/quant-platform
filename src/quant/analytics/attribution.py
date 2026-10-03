"""Brinson-Fachler allocation/selection/interaction attribution."""
from __future__ import annotations
import pandas as pd

def brinson_fachler(port_w,bench_w,port_r,bench_r)->pd.DataFrame:
    idx=sorted(set(port_w.index)|set(bench_w.index)|set(port_r.index)|set(bench_r.index))
    wp=port_w.reindex(idx).fillna(0).astype(float); wb=bench_w.reindex(idx).fillna(0).astype(float)
    rp=port_r.reindex(idx).fillna(0).astype(float); rb=bench_r.reindex(idx).fillna(0).astype(float)
    total_bench=float((wb*rb).sum())
    allocation=(wp-wb)*(rb-total_bench)
    selection=wb*(rp-rb)
    interaction=(wp-wb)*(rp-rb)
    return pd.DataFrame({"allocation":allocation,"selection":selection,"interaction":interaction,
                         "active_contribution":allocation+selection+interaction})
