# -*- coding: utf-8 -*-
"""比較切割演算法：舊(單一門檻掃描) vs 新(多組候選 + 用文字份量驗證)。
合成測試：拿現成音檔串成一個批次，間隔長度隨機，看能不能切回原樣。"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, sys, json, array, struct, random, re
sys.argv = ['x','k','1','1']
exec(open(_os.path.join(_HERE, 'gen_pack.py'), encoding='utf-8').read().split('# ==== 以下是主程式')[0])
sys.stdout.reconfigure(encoding='utf-8')

def envelope(a, rate):
    win = int(rate*0.02)
    return [max(abs(x) for x in a[i:i+win]) for i in range(0, len(a)-win, win)], win

def gapruns(lv, thr, minw):
    runs, cur = [], None
    for i, v in enumerate(lv):
        if v < thr:
            if cur is None: cur = i
        else:
            if cur is not None:
                if i-cur >= minw: runs.append((cur,i))
                cur = None
    if cur is not None and len(lv)-cur >= minw: runs.append((cur,len(lv)))
    return [r for r in runs if r[0] > 7 and r[1] < len(lv)-7]

def cut(a, lv, win, inner, want, rate):
    starts, ends = [0], []
    for r in inner: ends.append(r[0]); starts.append(r[1])
    ends.append(len(lv))
    pad = int(rate*0.06); thr = max(lv)*0.02; out=[]
    for i in range(want):
        a0,b0 = starts[i], ends[i]
        while a0<b0 and lv[a0]<thr: a0+=1
        while b0>a0 and lv[b0-1]<thr: b0-=1
        if b0<=a0: a0,b0 = starts[i],ends[i]
        out.append(a[max(0,a0*win-pad):min(len(a),b0*win+pad)])
    return out

def split_old(a, rate, want):
    lv,win = envelope(a,rate)
    if not lv or not max(lv): return None
    thr = max(lv)*0.02
    for mw in [17,25,35,45,60,80]:
        g = gapruns(lv,thr,mw)
        if len(g)==want-1: return cut(a,lv,win,g,want,rate)
        if len(g)<want-1: break
    return None

def syl(w):
    n=len(re.findall(r'[aeiouy]+',w.lower()))
    if w.lower().endswith('e') and n>1: n-=1
    return max(1,n)
def wgt(t): return sum(syl(x) for x in re.findall(r"[A-Za-z']+",t)) or 1

def spread(segs, items, rate):
    rs=[(len(s)/float(rate))/wgt(t) for s,t in zip(segs,items)]
    m=sum(rs)/len(rs)
    return max(abs(r-m) for r in rs)/m

def split_new(a, rate, items, tol):
    want=len(items)
    lv,win = envelope(a,rate)
    if not lv or not max(lv): return None
    thr = max(lv)*0.02
    cands=[]
    for mw in [17,25,35,45,60,80]:
        g=gapruns(lv,thr,mw)
        if len(g)==want-1: cands.append(g)
    allg=gapruns(lv,thr,15)
    if len(allg)>=want-1:
        cands.append(sorted(sorted(allg,key=lambda r:r[1]-r[0],reverse=True)[:want-1]))
    best=None; bs=9e9
    seen=set()
    for c in cands:
        k=tuple(c)
        if k in seen: continue
        seen.add(k)
        segs=cut(a,lv,win,c,want,rate)
        s=spread(segs,items,rate)
        if s<bs: bs=s; best=segs
    return best if best is not None and bs<=tol else None

TBL=[]
for u in range(256):
    v=~u&0xFF; t=(((v&0x0F)<<3)+132)<<((v&0x70)>>4)
    TBL.append((132-t) if (v&0x80) else (t-132))
OUT=_os.path.join(_ROOT, 'audio')
idx=json.load(io.open(OUT+'/index.json',encoding='utf-8'))
def rd(fn):
    b=open(OUT+'/'+fn,'rb').read(); i=12; data=None
    while i+8<=len(b):
        cid=b[i:i+4]; sz=struct.unpack('<I',b[i+4:i+8])[0]
        if cid==b'data': data=b[i+8:i+8+sz]
        i+=8+sz+(sz&1)
    return array.array('h',[TBL[x] for x in data])
sents=[k for k,v in idx.items() if v.startswith('s_')]
words=[k for k,v in idx.items() if not v.startswith('s_')]
N=60
def bench(pool,n,tol):
    random.seed(21)
    st={'old':[0,0,0],'new':[0,0,0]}     # 對 / 大錯 / 放棄
    for _ in range(N):
        picks=random.sample(pool,n); parts=[rd(idx[p]) for p in picks]
        buf=array.array('h',[0])*4000
        for i,p in enumerate(parts):
            buf.extend(p)
            if i<n-1: buf.extend(array.array('h',[0])*int(16000*random.uniform(0.4,2.0)))
        buf.extend(array.array('h',[0])*4000)
        for tag,segs in [('old',split_old(buf,16000,n)),('new',split_new(buf,16000,picks,tol))]:
            if segs is None: st[tag][2]+=1; continue
            err=max(abs(len(segs[i])-len(parts[i]))/16000.0 for i in range(n))
            st[tag][0 if err<=0.30 else 1]+=1
    return st
print(u'每組 %d 次合成測試，間隔隨機 0.4–2.0 秒'%N)
for tol in [0.85,0.60,0.45,0.35]:
    print(u'\n--- 驗證門檻 tol=%.2f ---'%tol)
    for label,pool,n in [(u'例句 5 項',sents,5),(u'例句 10 項',sents,10),(u'單字 10 項',words,10)]:
        st=bench(pool,n,tol)
        print(u'  %-10s 舊：對 %2d 大錯 %2d 放棄 %2d ｜ 新：對 %2d 大錯 %2d 放棄 %2d'
              %(label,st['old'][0],st['old'][1],st['old'][2],st['new'][0],st['new'][1],st['new'][2]))
