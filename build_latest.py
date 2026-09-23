import json, pathlib, requests, time, datetime, os, random

DATA_DIR = pathlib.Path("data")
HIST_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

# V5.10 V3稳定抓法回归版 - 腾讯为主，东财为辅，Session复用，不再被踢
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer':'https://gu.qq.com/',
})

def secid(code):
    code=str(code).zfill(6)
    return f'1.{code}' if code.startswith('6') else f'0.{code}'

def fetch_codes():
    # V3用的就是东财列表，这个不变，稳
    url="https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12"
    try:
        r=SESSION.get(url,timeout=20).json()
        codes=[str(d['f12']).zfill(6) for d in r['data']['diff']]
        codes=list(dict.fromkeys(codes))
        print(f"codes {len(codes)}")
        if len(codes)>=3000: return codes
    except Exception as e:
        print(f"codes fail {e}")
    # 兜底
    p=DATA_DIR/"codes.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return ["000001","600519","300750"]

def fetch_kline_tencent(code):
    # 腾讯日K，前复权，320天 - V3就是用的这个，最稳
    prefix='sh' if str(code).startswith('6') else 'sz'
    param=f"{prefix}{str(code).zfill(6)},day,,,360,qfq"
    url=f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
    try:
        r=SESSION.get(url,timeout=15)
        j=r.json()
        key=f"{prefix}{str(code).zfill(6)}"
        data=j.get('data',{}).get(key,{})
        klines=data.get('qfqday') or data.get('day') or []
        if len(klines)<60: return None
        bars=[]
        for k in klines:
            # k: [date, open, close, high, low, vol]
            try:
                d=k[0]; o=float(k[1]); c=float(k[2]); h=float(k[3]); l=float(k[4]); v=float(k[5])*100 # 腾讯手转股
                if c<=0: continue
                bars.append({"d":d,"o":o,"c":c,"h":h,"l":l,"v":v,"a":0})
            except: continue
        if len(bars)<60: return None
        # 去重按日期
        # 腾讯返回是新到旧？是旧到新
        return bars[-360:]
    except Exception as e:
        # print(f"tx {code} {e}")
        return None

def fetch_kline_eastmoney(code):
    sid=secid(code)
    url=f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&secid={sid}&beg=0&end=20500101&lmt=360"
    try:
        r=SESSION.get(url,timeout=15)
        j=r.json()
        klines=j.get('data',{}).get('klines',[])
        if len(klines)<60: return None
        bars=[]
        for line in klines:
            p=line.split(',')
            try:
                o=float(p[1]); c=float(p[2]); h=float(p[3]); l=float(p[4]); v=float(p[5])
                if c<=0: continue
                bars.append({"d":p[0],"o":o,"c":c,"h":h,"l":l,"v":v,"a":float(p[6])})
            except: continue
        if len(bars)<60: return None
        return bars
    except:
        return None

def fetch_kline_with_retry(code):
    # 先腾讯，失败再东财，重试3次，V3就是这么稳的
    for attempt in range(3):
        bars=fetch_kline_tencent(code)
        if bars and len(bars)>=60:
            return bars
        time.sleep(0.3+attempt*0.3)
        bars=fetch_kline_eastmoney(code)
        if bars and len(bars)>=60:
            return bars
        time.sleep(0.5+attempt*0.5+random.random()*0.3)
    print(f"k {code} FAIL after 3 attempts")
    return None

def main():
    codes=fetch_codes()
    (DATA_DIR/"codes.json").write_text(json.dumps(codes,ensure_ascii=False),encoding='utf-8')

    shard=int(os.getenv('SHARD','0'))
    total_shards=int(os.getenv('TOTAL_SHARDS','2'))
    chunk=(len(codes)+total_shards-1)//total_shards
    s=shard*chunk
    e=min(s+chunk, len(codes))
    target=codes[s:e]
    print(f"SHARD {shard}/{total_shards} {s}-{e} total {len(codes)} target {len(target)}")

    ok=0; fail=0
    for i,c in enumerate(target):
        bars=fetch_kline_with_retry(c)
        if bars is None:
            fail+=1
        else:
            try:
                (HIST_DIR/f"{c}.json").write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
                ok+=1
            except:
                fail+=1
        # V3的关键：慢一点，1秒1只，不被踢
        if i%20==0:
            print(f"[{i}/{len(target)}] {c} ok={ok} fail={fail} saved={len(list(HIST_DIR.glob('*.json')))}")
        time.sleep(0.8 + random.random()*0.4)  # 0.8-1.2秒，V3节奏

    meta={"updated":datetime.datetime.now().isoformat(),"count":len(codes),"shard":f"{shard}/{total_shards}","range":f"{s}-{e}","ok":ok,"fail":fail,"saved_total":len(list(HIST_DIR.glob("*.json"))),"v":"V5.10 V3稳定回归版-腾讯主源","note":"腾讯ifzq为主，不限速，东财为辅；Session复用，0.8-1.2秒/只，V3同样节奏所以稳；COST/ZQ/ZQ1今日参与，断档前端补"}
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)

if __name__=="__main__":
    main()
