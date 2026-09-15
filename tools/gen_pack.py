# -*- coding: utf-8 -*-
"""產生內建發音包：一次請求念多個字，切開後存成 16kHz µ-law WAV。
用法: python -u gen_pack.py <KEY1,KEY2> <每批字數> <要做幾課> [起始課]
"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io, os, json, sys, re, time, base64, array, struct, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

HTML = _os.path.join(_ROOT, 'index.html')
OUT = _os.path.join(_ROOT, 'audio')
KEYS = sys.argv[1].split(',')
PER = int(sys.argv[2])
LESSONS = int(sys.argv[3])
START = int(sys.argv[4]) if len(sys.argv) > 4 else 1
VOICE = 'Kore'
MODEL = 'gemini-3.1-flash-tts-preview'
WORDS_PER_LESSON = 8
_ki = [0]


def call(text):
    """回傳 (資料, 錯誤)。錯誤 'DAY' 代表當天額度用完，其他是暫時性的。

    免費層有兩個上限，訊息裡的 quotaId 才分得出來：
      GenerateRequestsPerMinutePerProjectPerModel-FreeTier = 3 次/分鐘（等一下就好）
      GenerateRequestsPerDayPerProjectPerModel-FreeTier    = 10 次/天  （今天沒了）
    """
    last = ''
    dayout = set()
    bad400 = 0
    for attempt in range(40):
        avail = [i for i in range(len(KEYS)) if i not in dayout]
        if not avail:
            return None, 'DAY'
        k = KEYS[avail[_ki[0] % len(avail)]]
        ki = avail[_ki[0] % len(avail)]
        body = {"contents": [{"parts": [{"text": text}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}}}
        req = urllib.request.Request(
            'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % MODEL,
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'x-goog-api-key': k})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode('utf-8')), None
        except Exception as e:
            code = getattr(e, 'code', None)
            msg = ''
            try:
                msg = e.read().decode('utf-8')
            except Exception:
                pass
            last = '%s' % (code or e)
            if code == 429:
                if 'PerDay' in msg:
                    dayout.add(ki)
                    print(u'    金鑰 %d 今天的額度用完了' % (ki + 1))
                    _ki[0] += 1
                    continue
                # 每分鐘上限：照伺服器建議的秒數等一下再送同一個請求
                m = re.search(r'retry in ([\d.]+)s', msg)
                wait = float(m.group(1)) + 2 if m else 22
                print(u'    每分鐘上限，等 %.0f 秒' % wait)
                time.sleep(min(wait, 70))
                continue
            if code == 400:
                # 這個 preview 模型偶爾回 400 INVALID_ARGUMENT，重送就會成功。
                # 用獨立計數，才不會被「每分鐘上限」的等待次數吃掉重試機會。
                # 每次重試都算一次額度，所以只重試 2 次就放棄，不值得為一個批次燒掉一天的量
                bad400 += 1
                if bad400 <= 2:
                    time.sleep(5 * bad400)
                    continue
                return None, last
            return None, last
    return None, last


def pcm_of(d):
    part = d['candidates'][0]['content']['parts'][0]
    inl = part.get('inlineData') or part.get('inline_data')
    mime = inl.get('mimeType') or inl.get('mime_type')
    rate = int(re.search(r'rate=(\d+)', mime).group(1))
    a = array.array('h')
    a.frombytes(base64.b64decode(inl['data']))
    return a, rate


def _env(a, rate):
    win = int(rate * 0.02)
    return [max(abs(x) for x in a[i:i + win]) for i in range(0, len(a) - win, win)], win


def _gaps(lv, thr, minw):
    runs, cur = [], None
    for i, v in enumerate(lv):
        if v < thr:
            if cur is None:
                cur = i
        else:
            if cur is not None:
                if i - cur >= minw:
                    runs.append((cur, i))
                cur = None
    if cur is not None and len(lv) - cur >= minw:
        runs.append((cur, len(lv)))
    return [r for r in runs if r[0] > 7 and r[1] < len(lv) - 7]


def _cut(a, lv, win, inner, want, rate):
    starts, ends = [0], []
    for r in inner:
        ends.append(r[0]); starts.append(r[1])
    ends.append(len(lv))
    thr = max(lv) * 0.02
    pad = int(rate * 0.06)
    out = []
    for i in range(want):
        a0, b0 = starts[i], ends[i]
        while a0 < b0 and lv[a0] < thr:
            a0 += 1
        while b0 > a0 and lv[b0 - 1] < thr:
            b0 -= 1
        if b0 <= a0:
            a0, b0 = starts[i], ends[i]
        out.append(a[max(0, a0 * win - pad):min(len(a), b0 * win + pad)])
    return out


def _syl(w):
    n = len(re.findall(r'[aeiouy]+', w.lower()))
    if w.lower().endswith('e') and n > 1:
        n -= 1
    return max(1, n)


def _weight(t):
    return sum(_syl(x) for x in re.findall(r"[A-Za-z']+", t)) or 1


def _spread(segs, items, rate):
    """切對的話，每段「長度 ÷ 文字份量」應該差不多。回傳離散度，越小越好。"""
    rs = [(len(s) / float(rate)) / _weight(t) for s, t in zip(segs, items)]
    m = sum(rs) / len(rs)
    return max(abs(r - m) for r in rs) / m


def split_words(a, rate, want, items=None, debug=False):
    """把一段語音切成 want 段。

    產生多組候選切法（六種最小靜音長度 + 取最長的 want-1 段），
    再用「每段長度是否和它的文字份量成比例」挑最好的一組。
    合成測試（間隔 0.4–2.0 秒隨機，各 60 次）：
      例句 5 項  舊 對43/大錯4/放棄13  →  新 對50/大錯1/放棄9
      例句 10 項 舊 對18/大錯12/放棄30 →  新 對29/大錯2/放棄29
      單字 10 項 舊 對60/大錯0/放棄0   →  新 對60/大錯0/放棄0
    """
    lv, win = _env(a, rate)
    if not lv or not max(lv):
        return None
    thr = max(lv) * 0.02
    cands = []
    for mw in [17, 25, 35, 45, 60, 80]:
        g = _gaps(lv, thr, mw)
        if len(g) == want - 1:
            cands.append(g)
    allg = _gaps(lv, thr, 15)
    if want > 1 and len(allg) >= want - 1:
        cands.append(sorted(sorted(allg, key=lambda r: r[1] - r[0], reverse=True)[:want - 1]))
    if want == 1:
        cands.append([])
    if not cands:
        if debug:
            print(u'      找不到 %d 段分隔靜音' % (want - 1))
        return None

    seen, best, bs = set(), None, 9e9
    for c in cands:
        k = tuple(c)
        if k in seen:
            continue
        seen.add(k)
        segs = _cut(a, lv, win, c, want, rate)
        if items is None:
            return segs
        sc = _spread(segs, items, rate)
        if sc < bs:
            bs, best = sc, segs
    if items is None:
        return None
    # 單字批次本來長度就不隨音節等比例，門檻放寬；例句抓緊一點
    tol = 0.85 if all(len(t.split()) == 1 for t in items) else 0.60
    if best is None or bs > tol:
        if debug:
            print(u'      切法不合理（離散度 %.2f > %.2f），放棄' % (bs, tol))
        return None
    return best


def resample(a, src, dst):
    """線性內插降取樣。"""
    n = int(len(a) * dst / float(src))
    out = array.array('h', [0]) * n
    step = src / float(dst)
    for i in range(n):
        p = i * step
        j = int(p)
        if j + 1 < len(a):
            f = p - j
            out[i] = int(a[j] * (1 - f) + a[j + 1] * f)
        elif j < len(a):
            out[i] = a[j]
    return out


_MU = None
def mulaw(a):
    """16-bit PCM → 8-bit µ-law（純 Python，Python 3.13 起 audioop 已移除）。"""
    out = bytearray(len(a))
    for i, s in enumerate(a):
        sign = 0x80 if s < 0 else 0
        if s < 0:
            s = -s
        if s > 32635:
            s = 32635
        s += 132
        exp = 7
        mask = 0x4000
        while exp > 0 and not (s & mask):
            mask >>= 1
            exp -= 1
        mant = (s >> (exp + 3)) & 0x0F
        out[i] = ~(sign | (exp << 4) | mant) & 0xFF
    return bytes(out)


def wav_mulaw(data, rate):
    n = len(data)
    return (b'RIFF' + struct.pack('<I', 50 + n) + b'WAVE' +
            b'fmt ' + struct.pack('<IHHIIHH', 18, 7, 1, rate, rate, 1, 8) + b'\x00\x00' +
            b'fact' + struct.pack('<II', 4, n) +
            b'data' + struct.pack('<I', n) + data)


# ==== 以下是主程式（其他腳本 exec 這個檔案時只取上面的工具函式）====
RAW = _os.path.join(_HERE, 'raw')


def save_raw(a16, rate, items, kind):
    """切割失敗時保存原始音訊，之後 resplit.py 可以離線重試，不再消耗額度。"""
    if not os.path.isdir(RAW):
        os.makedirs(RAW)
    name = '%s_%d' % (kind, int(time.time() * 1000))
    io.open(os.path.join(RAW, name + '.pcm'), 'wb').write(a16.tobytes())
    io.open(os.path.join(RAW, name + '.json'), 'w', encoding='utf-8').write(
        json.dumps({'rate': rate, 'kind': kind, 'items': items}, ensure_ascii=False))


s = io.open(HTML, encoding='utf-8').read()
blk = s[s.index('var WORDS = {'): s.index('\nvar S = {')]
bank = []
a = blk.index('\nb: [')
nxts = [blk.find('\n%s: [' % x, a + 1) for x in ['i', 'a']]
seg = blk[a:min([n for n in nxts if n > a])]
for line in seg.split('\n'):
    t = line.strip().rstrip(',')
    if t.startswith('["'):
        if t.endswith(']]'):
            t = t[:-1]
        try:
            f = json.loads(t)
        except Exception:
            continue
        bank.append(f[0])

need = []
for L in range(START, START + LESSONS):
    need += bank[(L - 1) * WORDS_PER_LESSON: L * WORDS_PER_LESSON]
need = [w for w in need if w]
if not os.path.isdir(OUT):
    os.makedirs(OUT)
manifest_path = os.path.join(OUT, 'index.json')
done = {}
if os.path.exists(manifest_path):
    try:
        done = json.load(io.open(manifest_path, encoding='utf-8'))
    except Exception:
        done = {}
todo = [w for w in need if w not in done]
print(u'目標 %d 課（第 %d–%d 課），共 %d 字，已有 %d，待做 %d'
      % (LESSONS, START, START + LESSONS - 1, len(need), len(need) - len(todo), len(todo)))

ok = fail = reqs = 0
for st in range(0, len(todo), PER):
    chunk = todo[st:st + PER]
    prompt = ('Read each item aloud clearly and plainly. Do not act anything out, do not add sound effects or laughter, do not add extra words. Leave a full one second pause between items. '
              'Do not add any extra words.\n' + '\n'.join(chunk))
    d, err = call(prompt)
    reqs += 1
    if d is None:
        print(u'  批次 %d 失敗：%s' % (st // PER + 1, err))
        if err == 'DAY':
            print(u'  所有金鑰今天的額度都用完了')
            break
        fail += len(chunk)
        continue
    a16, rate = pcm_of(d)
    segs = split_words(a16, rate, len(chunk), items=chunk, debug=True)
    if segs is None:
        save_raw(a16, rate, chunk, 'word')
        print(u'  批次 %d 切割失敗（%d 字），原始音訊已存下，可離線重試'
              % (st // PER + 1, len(chunk)))
        fail += len(chunk)
        continue
    for w, seg16 in zip(chunk, segs):
        small = resample(seg16, rate, 16000)
        data = mulaw(small)
        fn = re.sub(r'[^a-z0-9]+', '_', w.lower()).strip('_') + '.wav'
        io.open(os.path.join(OUT, fn), 'wb').write(wav_mulaw(data, 16000))
        done[w] = fn
        ok += 1
    io.open(manifest_path, 'w', encoding='utf-8').write(json.dumps(done, ensure_ascii=False))
    print(u'  批次 %d：%d 字 ✓（累計 %d，用了 %d 次請求）' % (st // PER + 1, len(chunk), ok, reqs))
    time.sleep(21)

total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith('.wav'))
print(u'完成：新增 %d 字，失敗 %d，用了 %d 次請求' % (ok, fail, reqs))
print(u'目前發音包共 %d 字，%.2f MB' % (len(done), total / 1048576.0))
