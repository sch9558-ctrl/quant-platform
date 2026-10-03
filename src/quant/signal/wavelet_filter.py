"""Wavelet denoising with PyWavelets when available and a safe Haar fallback."""
from __future__ import annotations
import math,numpy as np,pandas as pd

def _soft(x,t):return np.sign(x)*np.maximum(np.abs(x)-t,0.0)

def _haar_fallback(values,level=2):
    x=np.asarray(values,dtype=float).copy();n=len(x)
    if n<4:return x
    original_n=n;m=1<<(n-1).bit_length()
    if m>n:x=np.pad(x,(0,m-n),mode="edge")
    coeff=x.copy();length=len(coeff);levels=[]
    for _ in range(max(1,int(level))):
        if length<2:break
        a=(coeff[:length:2]+coeff[1:length:2])/math.sqrt(2);d=(coeff[:length:2]-coeff[1:length:2])/math.sqrt(2)
        levels.append((len(a),d.copy()));coeff[:len(a)]=a;coeff[len(a):length]=d;length=len(a)
    finest=levels[-1][1] if levels else np.array([0.]);sigma=np.median(np.abs(finest-np.median(finest)))/.6745 if len(finest) else 0.
    threshold=sigma*math.sqrt(2*math.log(len(coeff))) if sigma>0 else 0.
    for size,d in reversed(levels):
        a=coeff[:size].copy();dd=_soft(d,threshold);rec=np.empty(size*2);rec[0::2]=(a+dd)/math.sqrt(2);rec[1::2]=(a-dd)/math.sqrt(2);coeff[:size*2]=rec
    return coeff[:original_n]

def apply_wavelet_denoising(series:pd.Series,wavelet="db4",level=2)->pd.Series:
    s=pd.to_numeric(pd.Series(series,index=getattr(series,"index",None)),errors="coerce");clean=s.interpolate(limit_direction="both").to_numpy(dtype=float)
    if len(clean)<4:return s.copy()
    try:
        import pywt
        max_level=pywt.dwt_max_level(len(clean),pywt.Wavelet(wavelet).dec_len);use_level=max(1,min(int(level),max_level or 1))
        coeffs=pywt.wavedec(clean,wavelet,level=use_level,mode="symmetric");detail=coeffs[-1];sigma=np.median(np.abs(detail-np.median(detail)))/.6745 if len(detail) else 0.
        threshold=sigma*np.sqrt(2*np.log(len(clean))) if sigma>0 else 0.;coeffs=[coeffs[0]]+[_soft(c,threshold) for c in coeffs[1:]]
        restored=pywt.waverec(coeffs,wavelet,mode="symmetric")[:len(clean)]
    except ImportError:
        restored=_haar_fallback(clean,level)
    return pd.Series(restored,index=s.index,name=getattr(series,"name",None))
