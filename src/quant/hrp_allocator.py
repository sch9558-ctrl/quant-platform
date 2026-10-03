"""Hierarchical Risk Parity allocation."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

@dataclass(frozen=True)
class HRPResult:
    weights: pd.Series
    ordered_assets: tuple[str,...]
    linkage_matrix: np.ndarray

def _cluster_var(cov,items):
    sub=cov.loc[items,items]; ivp=1.0/np.diag(sub.to_numpy()); ivp=np.where(np.isfinite(ivp),ivp,0.0)
    w=ivp/ivp.sum() if ivp.sum()>0 else np.repeat(1/len(items),len(items))
    return float(w@sub.to_numpy()@w)

def _quasi_diag(link):
    link=link.astype(int); sort_ix=[int(link[-1,0]),int(link[-1,1])]; n=link[-1,3]
    while any(i>=n for i in sort_ix):
        new=[]
        for i in sort_ix:
            if i<n: new.append(i)
            else:
                row=link[i-n]; new.extend([int(row[0]),int(row[1])])
        sort_ix=new
    return sort_ix

def hrp_allocate(returns: pd.DataFrame, linkage_method="single") -> HRPResult:
    x=returns.astype(float).dropna(how="all")
    if x.shape[1]<2:
        return HRPResult(pd.Series(1.0,index=x.columns,dtype=float),tuple(x.columns),np.empty((0,4)))
    cov=x.cov(); corr=x.corr().clip(-1,1).fillna(0); dist=np.sqrt(np.maximum(0,0.5*(1-corr.to_numpy()))); np.fill_diagonal(dist,0)
    link=linkage(squareform(dist,checks=False),method=linkage_method); order=_quasi_diag(link); assets=list(cov.index[order]); w=pd.Series(1.0,index=assets)
    clusters=[assets]
    while clusters:
        nxt=[]
        for cluster in clusters:
            if len(cluster)<=1: continue
            mid=len(cluster)//2; c0=cluster[:mid]; c1=cluster[mid:]; v0=_cluster_var(cov,c0); v1=_cluster_var(cov,c1)
            alpha=1-v0/(v0+v1) if v0+v1>0 else .5; w[c0]*=alpha; w[c1]*=(1-alpha)
            if len(c0)>1: nxt.append(c0)
            if len(c1)>1: nxt.append(c1)
        clusters=nxt
    w=w/w.sum()
    return HRPResult(w.reindex(returns.columns),tuple(assets),link)
