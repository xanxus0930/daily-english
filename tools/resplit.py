# -*- coding: utf-8 -*-
"""離線重試切割失敗的批次：用存下來的原始音訊，不消耗任何額度。
用法: python -u resplit.py [--force]
  --force 允許放寬切點判定（只在確定要救的時候用，會列出每段長度供檢查）
"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, sys, json, re, array, hashlib
sys.argv_backup = sys.argv[:]
sys.argv = ['x', 'k', '1', '1']
exec(open(_os.path.join(_HERE, 'gen_pack.py'), encoding='utf-8').read().split('# ==== 以下是主程式')[0])
sys.argv = sys.argv_backup
sys.stdout.reconfigure(encoding='utf-8')
RAW = _os.path.join(_HERE, 'raw')
OUT = _os.path.join(_ROOT, 'audio')
mpath = os.path.join(OUT, 'index.json')
done = json.load(io.open(mpath, encoding='utf-8'))
if not os.path.isdir(RAW):
    print(u'沒有存下的失敗批次'); raise SystemExit
jobs = sorted(f for f in os.listdir(RAW) if f.endswith('.json'))
print(u'存下的失敗批次：%d 個' % len(jobs))
ok = 0
for j in jobs:
    meta = json.load(io.open(os.path.join(RAW, j), encoding='utf-8'))
    items = meta['items']; rate = meta['rate']; kind = meta['kind']
    todo = [x for x in items if x not in done]
    if not todo:
        os.remove(os.path.join(RAW, j)); os.remove(os.path.join(RAW, j[:-5] + '.pcm'))
        print(u'  %s 已經都有了，刪除' % j); continue
    a = array.array('h'); a.frombytes(open(os.path.join(RAW, j[:-5] + '.pcm'), 'rb').read())
    segs = split_words(a, rate, len(items), items=items, debug=True)
    if segs is None:
        print(u'  %s 還是切不開（%d 項）' % (j, len(items))); continue
    print(u'  %s 切開了：%s' % (j, [round(len(x)/float(rate), 2) for x in segs]))
    for txt, s16 in zip(items, segs):
        if txt in done: continue
        data = mulaw(resample(s16, rate, 16000))
        fn = ('s_' + hashlib.md5(txt.encode('utf-8')).hexdigest()[:12] + '.wav') if kind == 'sent' \
             else (re.sub(r'[^a-z0-9]+', '_', txt.lower()).strip('_') + '.wav')
        io.open(os.path.join(OUT, fn), 'wb').write(wav_mulaw(data, 16000))
        done[txt] = fn; ok += 1
    io.open(mpath, 'w', encoding='utf-8').write(json.dumps(done, ensure_ascii=False))
    os.remove(os.path.join(RAW, j)); os.remove(os.path.join(RAW, j[:-5] + '.pcm'))
print(u'離線救回 %d 筆，發音包共 %d 筆' % (ok, len(done)))
