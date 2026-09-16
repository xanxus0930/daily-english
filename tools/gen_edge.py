# -*- coding: utf-8 -*-
"""用 Microsoft Edge 神經語音（edge-tts）產生發音包。

跟 Gemini 版比：沒有每日額度、一次只念一個項目所以不用切割、例句檔案小一半多。
用法:
  python -u tools/gen_edge.py [--voice en-US-JennyNeural] [--level b|i|a|all] [--limit N]

- 產出 MP3，存到 audio/，檔名規則與 index.json 格式和原本相同（副檔名改 .mp3）
- 已經是 Jenny MP3 的項目會跳過；原本 Gemini 的 .wav 會被取代，舊 .wav 最後統一刪除
- 每 200 筆寫一次 index.json，中斷後重跑會從斷點繼續
"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import io, os, sys, json, re, time, hashlib, asyncio, argparse

sys.stdout.reconfigure(encoding='utf-8')

# 某些環境裡 aiohttp 的 c-ares 解析器連不到 DNS，改用系統解析
import aiohttp, aiohttp.resolver, aiohttp.connector
for _m in (aiohttp, aiohttp.resolver, aiohttp.connector):
    _m.DefaultResolver = aiohttp.resolver.ThreadedResolver
aiohttp.resolver.AsyncResolver = aiohttp.resolver.ThreadedResolver
import edge_tts

HTML = _os.path.join(_ROOT, 'index.html')
OUT = _os.path.join(_ROOT, 'audio')
MPATH = os.path.join(OUT, 'index.json')

ap = argparse.ArgumentParser()
ap.add_argument('--voice', default='en-US-JennyNeural')
ap.add_argument('--level', default='all')
ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--concurrency', type=int, default=4)
args = ap.parse_args()


def load_banks():
    s = io.open(HTML, encoding='utf-8').read()
    blk = s[s.index('var WORDS = {'):s.index('\nvar S = {')]
    keys = ['b', 'i', 'a']
    pos = {k: blk.index('\n%s: [' % k) for k in keys}
    order = sorted(pos.items(), key=lambda kv: kv[1])
    banks = {}
    for n, (k, p) in enumerate(order):
        end = order[n + 1][1] if n + 1 < len(order) else len(blk)
        rows = []
        for line in blk[p:end].split('\n'):
            t = line.strip().rstrip(',')
            if t.startswith('["'):
                if t.endswith(']]'):
                    t = t[:-1]
                try:
                    rows.append(json.loads(t))
                except Exception:
                    pass
        banks[k] = rows
    return banks


def fname(text, is_sentence):
    if is_sentence:
        return 's_' + hashlib.md5(text.encode('utf-8')).hexdigest()[:12] + '.mp3'
    # 只有英文字母、數字、空白的才直接用字當檔名；含其他符號的（right? / check-in）
    # 改用雜湊，否則會和 right / check in 撞成同一個檔、語氣被覆蓋
    if re.fullmatch(r'[A-Za-z0-9 ]+', text):
        return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_') + '.mp3'
    return 'w_' + hashlib.md5(text.encode('utf-8')).hexdigest()[:12] + '.mp3'


def main():
    banks = load_banks()
    levels = ['b', 'i', 'a'] if args.level == 'all' else [args.level]
    idx = json.load(io.open(MPATH, encoding='utf-8')) if os.path.exists(MPATH) else {}

    # 依課程順序排：先做每一課的單字與例句，這樣中途停下來時已完成的課是完整的
    todo, seen = [], set()
    for lv in levels:
        for f in banks[lv]:
            for text, is_s in ((f[0], False), (f[4], True)):
                if not text or text in seen:
                    continue
                seen.add(text)
                fn = fname(text, is_s)
                if idx.get(text) == fn and os.path.exists(os.path.join(OUT, fn)):
                    continue
                todo.append((text, fn))
    if args.limit:
        todo = todo[:args.limit]
    print(u'聲音 %s，要產生 %d 筆' % (args.voice, len(todo)))
    if not todo:
        return

    state = {'ok': 0, 'fail': [], 'since_save': 0}
    t0 = time.time()

    async def one(text, fn, sem):
        async with sem:
            path = os.path.join(OUT, fn)
            for attempt in range(4):
                try:
                    await edge_tts.Communicate(text, args.voice).save(path + '.part')
                    if os.path.getsize(path + '.part') < 800:
                        raise RuntimeError('檔案太小')
                    os.replace(path + '.part', path)
                    idx[text] = fn
                    state['ok'] += 1
                    state['since_save'] += 1
                    return
                except Exception as e:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    last = e
            state['fail'].append((text, str(last)[:80]))

    async def run():
        sem = asyncio.Semaphore(args.concurrency)
        batch = 200
        for st in range(0, len(todo), batch):
            await asyncio.gather(*(one(t, f, sem) for t, f in todo[st:st + batch]))
            io.open(MPATH, 'w', encoding='utf-8').write(json.dumps(idx, ensure_ascii=False))
            done = min(st + batch, len(todo))
            el = time.time() - t0
            eta = el / done * (len(todo) - done)
            print(u'  %d / %d（成功 %d、失敗 %d）已過 %.0f 秒，預估剩 %.0f 秒'
                  % (done, len(todo), state['ok'], len(state['fail']), el, eta))

    asyncio.run(run())

    # 刪掉沒有被 index.json 引用的舊檔（被 MP3 取代的 .wav、改過檔名的 .mp3）
    used = set(idx.values())
    removed = 0
    for f in os.listdir(OUT):
        if f.endswith(('.wav', '.mp3')) and f not in used:
            os.remove(os.path.join(OUT, f))
            removed += 1
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith(('.mp3', '.wav')))
    print(u'完成：成功 %d、失敗 %d，刪除沒用到的舊檔 %d 個。發音包共 %d 筆、%.1f MB，耗時 %.0f 秒'
          % (state['ok'], len(state['fail']), removed, len(idx), total / 1048576.0, time.time() - t0))
    for t, e in state['fail'][:20]:
        print(u'  失敗：%s  %s' % (t[:50], e))


if __name__ == '__main__':
    main()
