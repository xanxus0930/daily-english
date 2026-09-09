# -*- coding: utf-8 -*-
"""檢查「音檔內容有沒有對錯人」：長度應該和文字長度高度相關，離群者代表可能配錯。"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, json, sys, struct, re, math
sys.stdout.reconfigure(encoding='utf-8')
OUT = _os.path.join(_ROOT, 'audio')
TBL = []
for u in range(256):
    v = ~u & 0xFF
    t = (((v & 0x0F) << 3) + 132) << ((v & 0x70) >> 4)
    TBL.append((132 - t) if (v & 0x80) else (t - 132))

def dur(path):
    b = open(path, 'rb').read()
    i = 12; rate = 16000; n = 0
    while i + 8 <= len(b):
        cid = b[i:i+4]; sz = struct.unpack('<I', b[i+4:i+8])[0]
        if cid == b'fmt ': rate = struct.unpack('<HHII', b[i+8:i+20])[0+2]
        elif cid == b'data': n = sz
        i += 8 + sz + (sz & 1)
    return n / float(rate)

idx = json.load(io.open(os.path.join(OUT, 'index.json'), encoding='utf-8'))
def syl(w):
    w = w.lower(); n = len(re.findall(r'[aeiouy]+', w))
    if w.endswith('e') and n > 1: n -= 1
    return max(1, n)

def fit(pairs, label):
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
    n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
    sxy = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sxx = sum((x-mx)**2 for x in xs)
    b = sxy/sxx; a = my - b*mx
    res = [(y - (a + b*x)) for x, y in zip(xs, ys)]
    sd = math.sqrt(sum(r*r for r in res)/n)
    syy = sum((y-my)**2 for y in ys)
    r2 = 1 - sum(r*r for r in res)/syy
    out = sorted(zip([abs(r)/sd for r in res], [p[2] for p in pairs], ys, res), reverse=True)
    print(u'\n== %s：n=%d  預測式 秒=%.3f+%.3f*x  R²=%.3f  殘差SD=%.3fs ==' % (label, n, a, b, r2, sd))
    print(u'   離群（|殘差|>3SD）：')
    k = 0
    for z, t, y, r in out:
        if z <= 3.0: break
        k += 1; print(u'      %-42s 實際 %.2fs 偏離 %+.2fs (%.1f SD)' % (t[:42], y, r, z))
    if not k: print(u'      無')
    return sd

wp = []; sp = []
for t, fn in idx.items():
    d = dur(os.path.join(OUT, fn))
    if fn.startswith('s_'): sp.append((len(t), d, t))
    else: wp.append((syl(t) + 0.25*len(t), d, t))
fit(wp, u'單字（x = 音節數 + 0.25×字母數）')
fit(sp, u'例句（x = 字元數）')
