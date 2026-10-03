"""Hierarchical Risk Parity (HRP) allocator."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

def _cluster_var(cov:pd.DataFrame,items:list[str])->float:
    sub=cov.loc[items,items]
    inv=1/np.clip(np.diag(sub.values),1e-12,None); w=inv/inv.sum()
    return float(w@sub.values@w)

class HRPAllocator:
    def __init__(self,linkage_method:str="single"): self.linkage_method=linkage_method

    def allocate(self,returns:pd.DataFrame)->pd.Series:
        r=returns.dropna(how="all").fillna(0.0)
        if r.shape[1]==0:return pd.Series(dtype=float)
        if r.shape[1]==1:return pd.Series([1.0],index=r.columns)
        cov=r.cov(); corr=r.corr().clip(-1,1)
        dist=np.sqrt(np.maximum(0,0.5*(1-corr.values)))
        Z=linkage(squareform(dist,checks=False),method=self.linkage_method)
        ordered=list(corr.index[leaves_list(Z)])
        w=pd.Series(1.0,index=ordered)
        clusters=[ordered]
        while clusters:
            nxt=[]
            for cluster in clusters:
                if len(cluster)<=1: continue
                split=len(cluster)//2; c0=cluster[:split]; c1=cluster[split:]
                v0=_cluster_var(cov,c0); v1=_cluster_var(cov,c1)
                alpha=1-v0/(v0+v1) if v0+v1>0 else 0.5
                w.loc[c0]*=alpha; w.loc[c1]*=(1-alpha)
                if len(c0)>1:nxt.append(c0)
                if len(c1)>1:nxt.append(c1)
            clusters=nxt
        return (w/w.sum()).reindex(returns.columns).fillna(0.0)
