# -*- coding: utf-8 -*-
"""離線檢查發音包每一個音檔：切歪、截斷、殘留、無聲。不需要 API。"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, json, sys, struct, re
sys.stdout.reconfigure(encoding='utf-8')
OUT = _os.path.join(_ROOT, 'audio')
HTML = _os.path.join(_ROOT, 'index.html')

# G.711 µ-law 解碼表
TBL = []
for u in range(256):
    v = ~u & 0xFF
    t = (((v & 0x0F) << 3) + 132) << ((v & 0x70) >> 4)
    TBL.append((132 - t) if (v & 0x80) else (t - 132))

def load(path):
    b = open(path, 'rb').read()
    assert b[:4] == b'RIFF' and b[8:12] == b'WAVE', path
    i = 12; fmt = None; data = None
    while i + 8 <= len(b):
        cid = b[i:i+4]; sz = struct.unpack('<I', b[i+4:i+8])[0]; body = b[i+8:i+8+sz]
        if cid == b'fmt ': fmt = struct.unpack('<HHII', body[:12])
        elif cid == b'data': data = body
        i += 8 + sz + (sz & 1)
    code, ch, rate, _ = fmt
    return [TBL[x] for x in data], rate, code

def frames(sm, rate, ms=20):
    w = int(rate * ms / 1000.0)
    return [max(abs(x) for x in sm[i:i+w]) or 0 for i in range(0, max(1, len(sm)-w+1), w)], w

def analyse(path):
    sm, rate, code = load(path)
    dur = len(sm) / float(rate)
    lv, w = frames(sm, rate)
    peak = max(lv) if lv else 0
    if peak == 0:
        return dict(dur=dur, peak=0, silent=True)
    thr = peak * 0.04
    on = [i for i, v in enumerate(lv) if v >= thr]
    lead = on[0] * 0.02 if on else dur
    tail = (len(lv) - 1 - on[-1]) * 0.02 if on else dur
    # 內部長靜音（可能是兩個字黏在同一檔）
    gaps = []
    cur = None
    for i in range(on[0], on[-1] + 1) if on else []:
        if lv[i] < thr:
            if cur is None: cur = i
        else:
            if cur is not None:
                if (i - cur) * 0.02 >= 0.45: gaps.append((cur*0.02, i*0.02))
                cur = None
    # 開頭是否被切掉：第一個 frame 就已經很大聲
    onset_clip = lv[0] >= peak * 0.35
    tail_clip = lv[-1] >= peak * 0.35
    return dict(dur=dur, peak=peak, silent=False, lead=lead, tail=tail,
                gaps=gaps, onset_clip=onset_clip, tail_clip=tail_clip, code=code, rate=rate)

idx = json.load(io.open(os.path.join(OUT, 'index.json'), encoding='utf-8'))
words = {k: v for k, v in idx.items() if not v.startswith('s_')}
sents = {k: v for k, v in idx.items() if v.startswith('s_')}

def syl(w):
    w = w.lower()
    n = len(re.findall(r'[aeiouy]+', w))
    if w.endswith('e') and n > 1: n -= 1
    return max(1, n)

bad = {'silent': [], 'too_short': [], 'too_long': [], 'gap': [],
       'onset_clip': [], 'tail_clip': [], 'no_lead': [], 'fmt': []}
stats = []
for t, fn in idx.items():
    p = os.path.join(OUT, fn)
    a = analyse(p)
    stats.append((a['dur'], t))
    if a.get('silent'):
        bad['silent'].append(t); continue
    if a['code'] != 7 or a['rate'] != 16000:
        bad['fmt'].append((t, a['code'], a['rate']))
    if a['gaps']:
        bad['gap'].append((t[:40], [('%.2f-%.2f' % g) for g in a['gaps']]))
    if a['onset_clip']: bad['onset_clip'].append((t[:40], round(a['dur'], 2)))
    if a['tail_clip']: bad['tail_clip'].append((t[:40], round(a['dur'], 2)))
    if t in words:
        s = syl(t)
        if a['dur'] < 0.18 + 0.10 * s: bad['too_short'].append((t, round(a['dur'],2), s))
        if a['dur'] > 0.75 + 0.42 * s: bad['too_long'].append((t, round(a['dur'],2), s))
    else:
        n = len(t.split())
        if a['dur'] < n * 0.16: bad['too_short'].append((t[:40], round(a['dur'],2), n))
        if a['dur'] > n * 0.75 + 2.0: bad['too_long'].append((t[:40], round(a['dur'],2), n))

print(u'檔案 %d 個（單字 %d、例句 %d）' % (len(idx), len(words), len(sents)))
stats.sort()
print(u'長度 最短 %.2fs (%s)  最長 %.2fs  中位數 %.2fs'
      % (stats[0][0], stats[0][1][:25], stats[-1][0], stats[len(stats)//2][0]))
for k in ['silent', 'fmt', 'gap', 'onset_clip', 'tail_clip', 'too_short', 'too_long']:
    v = bad[k]
    print(u'\n== %s：%d ==' % (k, len(v)))
    for x in v[:25]: print('   ', x)
json.dump({k: [str(x) for x in v] for k, v in bad.items()},
          io.open('qc_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
