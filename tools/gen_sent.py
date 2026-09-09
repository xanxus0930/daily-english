# -*- coding: utf-8 -*-
"""產生例句發音。用法: python -u gen_sent.py <KEY1,KEY2> <每批句數> <做幾課>"""
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_HERE = _os.path.dirname(_os.path.abspath(__file__))
import io,os,sys,json,re,time,base64,array,struct,urllib.request,hashlib
sys.stdout.reconfigure(encoding='utf-8')
_argv=sys.argv[:]
sys.argv=['x',_argv[1],'1','1']
exec(open(_os.path.join(_HERE, 'gen_pack.py'), encoding='utf-8').read().split('# ==== 以下是主程式')[0])
sys.argv=_argv
PER=int(sys.argv[2]); LESSONS=int(sys.argv[3]); WPL=8
OUT=_os.path.join(_ROOT, 'audio'); HTML=_os.path.join(_ROOT, 'index.html')
s=io.open(HTML,encoding='utf-8').read()
blk=s[s.index('var WORDS = {'):s.index('\nvar S = {')]
a=blk.index('\nb: ['); nx=[blk.find('\n%s: ['%x,a+1) for x in ['i','a']]
seg=blk[a:min([n for n in nx if n>a])]
bank=[]
for line in seg.split('\n'):
    t=line.strip().rstrip(',')
    if t.startswith('["'):
        if t.endswith(']]'): t=t[:-1]
        try: f=json.loads(t)
        except: continue
        bank.append(f)
need=[]
for L in range(1,LESSONS+1):
    for f in bank[(L-1)*WPL:L*WPL]:
        need.append(f[4])
done=json.load(io.open(os.path.join(OUT,'index.json'),encoding='utf-8'))
todo=[x for x in need if x not in done]
print(u'例句 %d 句，已有 %d，待做 %d'%(len(need),len(need)-len(todo),len(todo)))
ok=fail=reqs=0
for st in range(0,len(todo),PER):
    chunk=todo[st:st+PER]
    prompt=('Read each item aloud clearly and plainly. Do not act anything out, do not add sound effects or laughter, do not add extra words. Leave a full one second pause between items. '
            'Do not add any extra words.\n'+'\n'.join(chunk))
    d,err=call(prompt); reqs+=1
    if d is None:
        print(u'  批次 %d 失敗：%s'%(st//PER+1,err))
        if err=='DAY':
            print(u'  所有金鑰今天的額度都用完了'); break
        fail+=len(chunk); continue
    a16,rate=pcm_of(d)
    segs=split_words(a16,rate,len(chunk),items=chunk,debug=True)
    if segs is None:
        save_raw(a16,rate,chunk,'sent')
        print(u'  批次 %d 切割失敗（%d 句），原始音訊已存下，可離線重試'%(st//PER+1,len(chunk)))
        fail+=len(chunk); continue
    for txt,s16 in zip(chunk,segs):
        data=mulaw(resample(s16,rate,16000))
        fn='s_'+hashlib.md5(txt.encode('utf-8')).hexdigest()[:12]+'.wav'
        io.open(os.path.join(OUT,fn),'wb').write(wav_mulaw(data,16000))
        done[txt]=fn; ok+=1
    io.open(os.path.join(OUT,'index.json'),'w',encoding='utf-8').write(json.dumps(done,ensure_ascii=False))
    print(u'  批次 %d：%d 句（累計 %d，%d 次請求）'%(st//PER+1,len(chunk),ok,reqs))
    time.sleep(21)
tot=sum(os.path.getsize(os.path.join(OUT,f)) for f in os.listdir(OUT) if f.endswith('.wav'))
print(u'新增 %d 句，失敗 %d，%d 次請求。發音包共 %d 筆，%.2f MB'%(ok,fail,reqs,len(done),tot/1048576.0))
