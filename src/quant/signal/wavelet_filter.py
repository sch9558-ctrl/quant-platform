"""Discrete-wavelet price denoising."""
from __future__ import annotations
import numpy as np
import pandas as pd

def apply_wavelet_denoising(series:pd.Series,wavelet:str="db4",level:int=2)->pd.Series:
    import pywt
    s=pd.Series(series,dtype=float)
    clean=s.interpolate(limit_direction="both")
    if len(clean)<8:return clean
    max_level=pywt.dwt_max_level(len(clean),pywt.Wavelet(wavelet).dec_len)
    if max_level<=0:return clean
    lvl=min(max(1,int(level)),max_level)
    coeffs=pywt.wavedec(clean.values,wavelet,level=lvl,mode="symmetric")
    detail=np.concatenate([np.asarray(c) for c in coeffs[1:] if len(c)]) if len(coeffs)>1 else np.array([0.0])
    sigma=np.median(np.abs(detail))/0.6745 if len(detail) else 0.0
    threshold=sigma*np.sqrt(2*np.log(len(clean))) if sigma>0 else 0.0
    filtered=[coeffs[0]]+[pywt.threshold(c,threshold,mode="soft") for c in coeffs[1:]]
    recon=pywt.waverec(filtered,wavelet,mode="symmetric")[:len(clean)]
    return pd.Series(recon,index=s.index,name=s.name)
