# -*- coding: utf-8 -*-
"""把「單字與例句以外」也會被朗讀的句子加進發音包。

使用者的 iPhone 內建語音念不出來（實測：3 秒內不發聲，但英文語音清單有 26 個），
所以任何需要朗讀的內容都必須有自己的音檔，不能退回手機語音。

涵蓋：
  - 文法課的例句（文法課頁面、課堂文法步驟、聽寫題庫都會念）
  - 多益 Part 2 的題目與三個選項（聽力題、聽寫題庫會念）
多益 Part 5/6/7 是閱讀題，不朗讀，所以不產。

用法: python -u tools/gen_extra.py [--voice en-US-JennyNeural] [--concurrency 6] [--dry]
"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import io, os, sys, json, re, time, hashlib, asyncio, argparse

sys.stdout.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('--voice', default='en-US-JennyNeural')
ap.add_argument('--concurrency', type=int, default=6)
ap.add_argument('--dry', action='store_true')
args = ap.parse_args()

HTML = _os.path.join(_ROOT, 'index.html')
OUT = _os.path.join(_ROOT, 'audio')
MPATH = os.path.join(OUT, 'index.json')
src = io.open(HTML, encoding='utf-8').read()


def read_js_string(s, k):
    """從 s[k] 的雙引號開始讀一個 JS 字串，回傳 (值, 結束位置)。"""
    assert s[k] == '"'
    k += 1
    buf = []
    while k < len(s):
        c = s[k]
        if c == '\\':
            nxt = s[k + 1]
            buf.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\', "'": "'", '/': '/'}.get(nxt, nxt))
            k += 2
            continue
        if c == '"':
            return ''.join(buf), k + 1
        buf.append(c)
        k += 1
    return ''.join(buf), k


texts = []

# ── 單字卡的延伸片語（第 8 欄，格式 "phrase=中文/phrase2=中文2"）──
blk = src[src.index('var WORDS = {'):src.index('\nvar S = {')]
for line in blk.split('\n'):
    t = line.strip().rstrip(',')
    if not t.startswith('["'):
        continue
    if t.endswith(']]'):
        t = t[:-1]
    try:
        f = json.loads(t)
    except Exception:
        continue
    if len(f) > 7 and f[7]:
        for item in f[7].split('/'):
            en = item.split('=')[0].strip()
            if en:
                texts.append(('延伸片語', en))

# ── 文法例句：GRAMMAR 是單行 JSON，直接解析 ──
i = src.index('var GRAMMAR = ')
body = src[i + len('var GRAMMAR = '):src.index('\n', i)].rstrip().rstrip(';')
for lesson in json.loads(body):
    for e in lesson.get('examples', []):
        if e.get('en'):
            texts.append(('文法例句', e['en']))

# ── 多益 Part 2：題目與三個選項 ──
p2s = src.index('\np2: [')
p2e = src.index('\n],', p2s)
blk = src[p2s:p2e]
k = 0
while True:
    m = re.compile(r'\bq:\s*"').search(blk, k)
    if not m:
        break
    q, k = read_js_string(blk, m.end() - 1)
    texts.append(('多益題目', q))
    mo = re.compile(r'\bo:\s*\[').search(blk, k)
    if not mo:
        continue
    k = mo.end()
    while True:
        while k < len(blk) and blk[k] in ' \t\n':
            k += 1
        if k >= len(blk) or blk[k] != '"':
            break
        v, k = read_js_string(blk, k)
        texts.append(('多益選項', v))
        while k < len(blk) and blk[k] in ' \t\n':
            k += 1
        if k < len(blk) and blk[k] == ',':
            k += 1
            continue
        break


def ok(t):
    t = (t or '').strip()
    if not t or len(t) > 220:
        return False
    if not re.search(r'[A-Za-z]', t):
        return False
    if re.search(r'[一-鿿]', t):
        return False
    if '____' in t:           # 填空題不朗讀
        return False
    return True


idx = json.load(io.open(MPATH, encoding='utf-8'))
seen, todo, by_kind = set(), [], {}
for kind, t in texts:
    t = (t or '').strip()
    if not ok(t) or t in seen:
        continue
    seen.add(t)
    by_kind[kind] = by_kind.get(kind, 0) + 1
    if t not in idx:
        todo.append(t)

print(u'會被朗讀的句子：%s（合計 %d）' % (
    '、'.join('%s %d' % (k, v) for k, v in by_kind.items()), len(seen)))
print(u'其中還沒有音檔的：%d' % len(todo))
for t in todo[:3]:
    print(u'  例如：%s' % t[:70])
if args.dry or not todo:
    raise SystemExit

import aiohttp, aiohttp.resolver, aiohttp.connector
for _m in (aiohttp, aiohttp.resolver, aiohttp.connector):
    _m.DefaultResolver = aiohttp.resolver.ThreadedResolver
aiohttp.resolver.AsyncResolver = aiohttp.resolver.ThreadedResolver
import edge_tts

state = {'ok': 0, 'fail': []}
t0 = time.time()


def fname(text):
    if re.fullmatch(r'[A-Za-z0-9 ]+', text):
        return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_') + '.mp3'
    return 'w_' + hashlib.md5(text.encode('utf-8')).hexdigest()[:12] + '.mp3'


async def one(text, sem):
    fn = (fname(text) if len(text.split()) <= 4
          else 's_' + hashlib.md5(text.encode('utf-8')).hexdigest()[:12] + '.mp3')
    path = os.path.join(OUT, fn)
    async with sem:
        last = None
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, args.voice).save(path + '.part')
                if os.path.getsize(path + '.part') < 800:
                    raise RuntimeError('檔案太小')
                os.replace(path + '.part', path)
                idx[text] = fn
                state['ok'] += 1
                return
            except Exception as e:
                last = e
                await asyncio.sleep(1.5 * (attempt + 1))
        state['fail'].append((text, str(last)[:60]))


async def run():
    sem = asyncio.Semaphore(args.concurrency)
    for st in range(0, len(todo), 200):
        await asyncio.gather(*(one(t, sem) for t in todo[st:st + 200]))
        io.open(MPATH, 'w', encoding='utf-8').write(json.dumps(idx, ensure_ascii=False))
        print(u'  %d / %d（成功 %d、失敗 %d）' % (min(st + 200, len(todo)), len(todo), state['ok'], len(state['fail'])))

asyncio.run(run())
total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith('.mp3'))
print(u'完成：成功 %d、失敗 %d。發音包共 %d 筆、%.1f MB，耗時 %.0f 秒'
      % (state['ok'], len(state['fail']), len(idx), total / 1048576.0, time.time() - t0))
for t, e in state['fail'][:10]:
    print(u'  失敗：%s  %s' % (t[:50], e))
