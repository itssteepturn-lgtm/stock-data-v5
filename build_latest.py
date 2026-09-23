import json, pathlib, requests, time, datetime, os

DATA_DIR = pathlib.Path("data")
HIST_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

# V5.8 最终最稳自养版 - 保护COST/ZQ/ZQ1，支持断档检测
def secid(code):
    code=str(code).zfill(6)
    return f'1.{code}' if code.startswith('6') else f'0.{code}'

def fetch_codes():
    url="https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12"
    try:
        r=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0'}).json()
        codes=[str(d['f12']).zfill(6) for d in r['data']['diff'] if d['f12']]
        codes=list(dict.fromkeys(codes))
        print(f"codes {len(codes)}")
        return codes
    except Exception as e:
        print(f"codes fail {e}")
        p=DATA_DIR/"codes.json"
        if p.exists():
            try: return json.loads(p.read_text())
            except: pass
        return ["000001","399006","600519","300750","300313"]

def fetch_kline(code):
    sid=secid(code)
    url=f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&secid={sid}&beg=0&end=20500101&lmt=360"
    try:
        r=requests.get(url,timeout=12,headers={'User-Agent':'Mozilla/5.0'}).json()
        klines=r.get('data',{}).get('klines',[])
        if len(klines)<60: return None
        bars=[]; closes=set()
        for line in klines:
            p=line.split(',')
            try:
                o=float(p[1]); c=float(p[2]); h=float(p[3]); l=float(p[4]); v=float(p[5])
                if c<=0: continue
                closes.add(c)
                bars.append({"d":p[0],"o":o,"c":c,"h":h,"l":l,"v":v,"a":float(p[6])})
            except: continue
        if len(bars)<60 or len(closes)<5: return None
        return bars
    except Exception as e:
        print(f"k {code} {e}")
        return None

def main():
    codes=fetch_codes()
    (DATA_DIR/"codes.json").write_text(json.dumps(codes,ensure_ascii=False),encoding='utf-8')
    shard=int(os.getenv('SHARD','0'))
    total_shards=int(os.getenv('TOTAL_SHARDS','2'))
    chunk=(len(codes)+total_shards-1)//total_shards
    s=shard*chunk
    e=min(s+chunk,len(codes))
    target=codes[s:e]
    print(f"SHARD {shard}/{total_shards} {s}-{e} {len(target)}")
    ok=0; fail=0
    for i,c in enumerate(target):
        bars=fetch_kline(c)
        if bars is None:
            fail+=1
        else:
            try:
                (HIST_DIR/f"{c}.json").write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
                ok+=1
            except:
                fail+=1
        if i%100==0: print(f"{i}/{len(target)} {c} ok={ok} fail={fail}")
        time.sleep(0.05)
    meta={"updated":datetime.datetime.now().isoformat(),"count":len(codes),"shard":f"{shard}/{total_shards}","range":f"{s}-{e}","ok":ok,"fail":fail,"saved_total":len(list(HIST_DIR.glob("*.json"))),"v":"V5.8 最稳自养-断档保护版","note":"自养只到昨日，今日由前端捏合；COST/ZQ/ZQ1全部参与今日计算，陡升当日可见；前端会补齐5天前等断档"}
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)

if __name__=="__main__":
    main()
