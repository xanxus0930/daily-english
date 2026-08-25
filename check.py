# -*- coding: utf-8 -*-
"""部署前自動檢查（純 Python，不需要 node）。
用法：python check.py [要檢查的 HTML 檔，預設 index.html]
檢查項目：
  1. 必要檔案是否齊全
  2. manifest.webmanifest 是否為合法 JSON、欄位齊全
  3. 圖示 PNG 是否存在且尺寸正確
  4. sw.js 是否含必要事件與入口檔名
  5. HTML 內 <script> 的括號／引號是否平衡（粗略語法檢查）
  6. WORDS 三個等級是否有陣列破洞（漏逗號／多逗號）
  7. TOEIC 題庫完整性（選項數、答案索引、必要欄位）
  8. 程式參照的 DOM id 是否都存在於 HTML
"""
import io, os, re, json, struct, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
fails, warns = [], []


def ok(msg):
    print('  [OK] ' + msg)


def fail(msg):
    fails.append(msg)
    print('  [FAIL] ' + msg)


def warn(msg):
    warns.append(msg)
    print('  [WARN] ' + msg)


def path(name):
    return os.path.join(ROOT, name)


print('== 1. 必要檔案 ==')
required = [HTML, 'sw.js', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png']
for f in required:
    if os.path.exists(path(f)):
        ok('%s (%d bytes)' % (f, os.path.getsize(path(f))))
    else:
        fail('缺少 ' + f)

if not os.path.exists(path(HTML)):
    print('\n無法繼續：找不到 %s' % HTML)
    raise SystemExit(1)

src = io.open(path(HTML), encoding='utf-8').read()

print('== 2. manifest ==')
try:
    mf = json.loads(io.open(path('manifest.webmanifest'), encoding='utf-8').read())
    for k in ['name', 'start_url', 'display', 'icons']:
        if k not in mf:
            fail('manifest 缺少欄位 ' + k)
    if mf.get('display') != 'standalone':
        warn('display 不是 standalone，加入主畫面不會全螢幕')
    for ic in mf.get('icons', []):
        if not os.path.exists(path(ic['src'].lstrip('./'))):
            fail('manifest 指到不存在的圖示 ' + ic['src'])
    ok('JSON 合法，%d 組圖示' % len(mf.get('icons', [])))
except Exception as e:
    fail('manifest 解析失敗: %s' % e)

print('== 3. 圖示尺寸 ==')
for f, expect in [('icon-180.png', 180), ('icon-192.png', 192), ('icon-512.png', 512)]:
    try:
        with open(path(f), 'rb') as fh:
            head = fh.read(24)
        if head[:8] != b'\x89PNG\r\n\x1a\n':
            fail('%s 不是合法 PNG' % f)
            continue
        w, h = struct.unpack('>II', head[16:24])
        if (w, h) != (expect, expect):
            fail('%s 尺寸是 %dx%d，應為 %dx%d' % (f, w, h, expect, expect))
        else:
            ok('%s %dx%d' % (f, w, h))
    except Exception as e:
        fail('%s 讀取失敗: %s' % (f, e))

print('== 4. service worker ==')
sw = io.open(path('sw.js'), encoding='utf-8').read()
for token in ["addEventListener('install'", "addEventListener('activate'", "addEventListener('fetch'"]:
    if token not in sw:
        fail('sw.js 缺少 ' + token)
if "'./index.html'" not in sw and 'ENTRY' not in sw:
    fail('sw.js 沒有指向入口檔')
m = re.search(r"var CACHE = '([^']+)'", sw)
ok('快取版本 %s' % (m.group(1) if m else '未知'))
if HTML != 'index.html':
    warn('目前檢查的是 %s，但 sw.js 的入口是 index.html；部署前請改名' % HTML)

print('== 5. HTML 內 JS 語法檢查 ==')
scripts = re.findall(r'<script>(.*?)</script>', src, re.S)
if not scripts:
    fail('找不到 <script> 區塊')
else:
    ok('找到 %d 個 script 區塊（共 %d 字元）' % (len(scripts), sum(len(x) for x in scripts)))
    import subprocess, tempfile, shutil
    node = shutil.which('node')
    if not node:
        warn('環境沒有 node，略過真正的 JS 語法檢查（安裝 node 後本項會自動啟用）')
    else:
        for i, js in enumerate(scripts):
            tf = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
            tf.write(js); tf.close()
            r = subprocess.run([node, '--check', tf.name], capture_output=True, text=True)
            os.unlink(tf.name)
            if r.returncode == 0:
                ok('script #%d 語法正確' % i)
            else:
                fail('script #%d 語法錯誤: %s' % (i, (r.stderr or '').strip().split(chr(10))[0]))
    for fn in ['function goScreen(', 'function initDaily(', 'function buildQuiz(', 'function callGemini(']:
        if fn not in src:
            fail('缺少關鍵函式 ' + fn)

print('== 6. 單字庫 ==')
try:
    wblock = src[src.index('var WORDS = {'): src.index('\nvar S = {')]
    total = 0
    for lv in ['b', 'i', 'a']:
        seg_start = wblock.index('\n%s: [' % lv)
        seg_end = len(wblock)
        for nxt in ['b', 'i', 'a']:
            if nxt == lv:
                continue
            k = wblock.find('\n%s: [' % nxt, seg_start + 1)
            if k > seg_start:
                seg_end = min(seg_end, k)
        seg = wblock[seg_start:seg_end]
        rows = re.findall(r'^\s*\["', seg, re.M)
        holes = re.findall(r',\s*,', seg)
        missing_comma = re.findall(r'\]\s*\n\s*\[', seg)
        if holes:
            fail('%s 等級有 %d 處連續逗號（會產生空元素）' % (lv, len(holes)))
        if missing_comma:
            fail('%s 等級有 %d 處缺少分隔逗號（會被當成索引運算）' % (lv, len(missing_comma)))
        bad_len = 0
        for line in seg.split('\n'):
            t = line.strip().rstrip(',')
            if t.startswith('["') and t.endswith(']'):
                if t.count('", "') != 9:
                    bad_len += 1
        if bad_len:
            fail('%s 等級有 %d 筆欄位數不是 10' % (lv, bad_len))
        total += len(rows)
        ok('%s 等級 %d 字' % (lv, len(rows)))
    ok('單字合計 %d' % total)
except Exception as e:
    fail('單字庫檢查失敗: %s' % e)

print('== 7. 多益題庫 ==')
try:
    tblock = src[src.index('var TOEIC = {'): src.index('var tState = null;')]
    p5 = re.findall(r'\{q:"[^\n]*?a:(\d)[^\n]*?\},?\n', tblock)
    opts_bad = 0
    for line in tblock.split('\n'):
        t = line.strip()
        if t.startswith('{q:"') and ' o:[' in t:
            n = t.count('","') + 1 if '","' in t else 0
            m2 = re.search(r'o:\[(.*?)\], a:(\d)', t)
            if m2:
                nopt = len(re.findall(r'"(?:[^"\\]|\\.)*"', m2.group(1)))
                a = int(m2.group(2))
                if nopt not in (3, 4) or a >= nopt:
                    opts_bad += 1
    if opts_bad:
        fail('有 %d 題選項數或答案索引異常' % opts_bad)
    else:
        ok('題目選項與答案索引檢查通過')
    for part in ['p5', 'p2', 'p6', 'p7']:
        if part + ': [' not in tblock:
            fail('缺少 %s 題庫' % part)
    ok('四種題型皆存在')
except Exception as e:
    fail('多益題庫檢查失敗: %s' % e)

print('== 8. DOM id 參照 ==')
ids_used = set(re.findall(r"getElementById\('([^']+)'\)", src))
ids_defined = set(re.findall(r'id="([^"]+)"', src))
dynamic = {'q-fill-inp', 'q-fb', 'typing-bubble', 'tq-script', 'tq-fb', 'tq-ai-status', 'weak-chips',
           'gm-fb', 'dt-inp', 'dt-res', 'cls-fb', 'cls-dict-inp', 'cls-dict-res'}
missing = sorted(ids_used - ids_defined - dynamic)
if missing:
    fail('程式用到但 HTML 沒有的 id: %s' % ', '.join(missing))
else:
    ok('%d 個 id 全部對得上（%d 個為動態產生）' % (len(ids_used), len(dynamic)))

print('\n===== 結果 =====')
print('FAIL %d, WARN %d' % (len(fails), len(warns)))
for f in fails:
    print(' FAIL:', f)
for w in warns:
    print(' WARN:', w)
raise SystemExit(1 if fails else 0)
