# -*- coding: utf-8 -*-
"""難切的字改成一次請求只念一個，不做切割，只修剪頭尾靜音。
用法: python -u gen_one.py <KEY1,KEY2> <字1> <字2> ...
"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, sys, json, re, time, array
sys.argv_backup = sys.argv[:]
sys.argv = ['x', sys.argv_backup[1], '1', '1']
exec(open(_os.path.join(_HERE, 'gen_pack.py'), encoding='utf-8').read().split('# ==== 以下是主程式')[0])
sys.argv = sys.argv_backup
sys.stdout.reconfigure(encoding='utf-8')
OUT = _os.path.join(_ROOT, 'audio')
mpath = os.path.join(OUT, 'index.json')
done = json.load(io.open(mpath, encoding='utf-8'))
words = sys.argv[2:]
ok = 0
for w in words:
    if w in done:
        print(u'%s 已有，跳過' % w); continue
    d, err = call('Say this English word aloud once, clearly and plainly, '
                  'as a dictionary pronunciation. Say nothing else.\n' + w)
    if d is None:
        print(u'%s 失敗：%s' % (w, err))
        if err == '429': break
        continue
    a, rate = pcm_of(d)
    win = int(rate * 0.02)
    lv = [max(abs(x) for x in a[i:i+win]) for i in range(0, len(a)-win, win)]
    peak = max(lv) if lv else 0
    if not peak:
        print(u'%s 全靜音，跳過' % w); continue
    thr = peak * 0.04
    on = [i for i, v in enumerate(lv) if v >= thr]
    pad = int(rate * 0.06)
    seg = a[max(0, on[0]*win - pad): min(len(a), (on[-1]+1)*win + pad)]
    dur = len(seg) / float(rate)
    if dur > 2.2 or dur < 0.2:
        print(u'%s 長度異常 %.2fs，跳過' % (w, dur)); continue
    data = mulaw(resample(seg, rate, 16000))
    fn = re.sub(r'[^a-z0-9]+', '_', w.lower()).strip('_') + '.wav'
    io.open(os.path.join(OUT, fn), 'wb').write(wav_mulaw(data, 16000))
    done[w] = fn; ok += 1
    io.open(mpath, 'w', encoding='utf-8').write(json.dumps(done, ensure_ascii=False))
    print(u'%s ✓ %.2fs' % (w, dur))
    time.sleep(1)
print(u'完成 %d/%d，發音包共 %d 筆' % (ok, len(words), len(done)))
