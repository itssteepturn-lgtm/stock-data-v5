import json, pathlib, requests, time, datetime, os, random

DATA_DIR = pathlib.Path("data")
HIST_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

def secid(code):
    code=str(code).zfill(6)
    return f'1.{code}' if code.startswith('6') else f'0.{code}'

def fetch_codes():
    # 更稳的接口，多试几次
    urls=[
        "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12",
        "https://push2.eastmoney.com/api/qt/clist/get?pn=2&pz=6000&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12",
    ]
    codes=[]
    for url in urls:
        try:
            r=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0','Referer':'https://eastmoney.com'}).json()
            diff=r.get('data',{}).get('diff',[])
            for d in diff:
                c=str(d.get('f12','')).zfill(6)
                if c and c!='000000':
                    codes.append(c)
            if len(codes)>=4000: break
            time.sleep(0.5)
        except Exception as e:
            print(f"codes url fail {e}")
    codes=list(dict.fromkeys(codes))
    # 如果还是少，用已有codes.json补
    if len(codes)<1000:
        p=DATA_DIR/"codes.json"
        if p.exists():
            try:
                old=json.loads(p.read_text())
                codes=list(dict.fromkeys(codes+old))
            except: pass
    print(f"codes final {len(codes)}")
    if len(codes)<100:
        # 兜底核心50只，保证这次能跑通
        return ["000001","399001","399006","600519","000858","300750","600000","000063","600036","601318"] + [f"{i:06d}" for i in range(1,51)]
    return codes

def fetch_kline_with_retry(code, retries=3):
    sid=secid(code)
    url=f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&secid={sid}&beg=0&end=20500101&lmt=360"
    for attempt in range(retries):
        try:
            r=requests.get(url,timeout=15,headers={'User-Agent':'Mozilla/5.0','Referer':'https://eastmoney.com'})
            j=r.json()
            klines=j.get('data',{}).get('klines',[])
            if len(klines)<60:
                time.sleep(0.5+attempt*0.5)
                continue
            bars=[]; closes=set()
            for line in klines:
                p=line.split(',')
                try:
                    o=float(p[1]); c=float(p[2]); h=float(p[3]); l=float(p[4]); v=float(p[5])
                    if c<=0: continue
                    closes.add(c)
                    bars.append({"d":p[0],"o":o,"c":c,"h":h,"l":l,"v":v,"a":float(p[6])})
                except: continue
            if len(bars)<60 or len(closes)<5:
                time.sleep(0.5+attempt*0.5)
                continue
            return bars
        except Exception as e:
            print(f"k {code} attempt {attempt} err {e}")
            time.sleep(1+attempt*1 + random.random())
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

    # 清理假数据：检测旧文件如果是随机假数据（c在10-11之间），删掉
    cleaned=0
    for f in HIST_DIR.glob("*.json"):
        try:
            j=json.loads(f.read_text())
            arr=j.get('bars',j) if isinstance(j,dict) else j
            if not arr: continue
            # 假数据特征：c在10-11随机，v=1000
            fake=0
            for b in arr[:5]:
                c=b.get('c',0) if isinstance(b,dict) else 0
                v=b.get('v',0) if isinstance(b,dict) else 0
                if 9.5<c<11.5 and abs(v-1000)<1:
                    fake+=1
            if fake>=3:
                f.unlink()
                cleaned+=1
        except: pass
    print(f"cleaned fake {cleaned}")

    ok=0; fail=0
    for i,c in enumerate(target):
        # 如果已存在真数据且今天已更新，跳过（避免重复被限）
        existing=HIST_DIR/f"{c}.json"
        if existing.exists():
            try:
                j=json.loads(existing.read_text())
                arr=j if isinstance(j,list) else j.get('bars',[])
                if arr and len(arr)>=60:
                    # 检查是否是今天之前的数据，如果是今天的不重复抓
                    last_d=arr[-1].get('d','') if isinstance(arr[-1],dict) else ''
                    if last_d and last_d>=datetime.date.today().isoformat():
                        ok+=1
                        continue
            except: pass

        bars=fetch_kline_with_retry(c)
        if bars is None:
            fail+=1
            if i%20==0: print(f"[{i}/{len(target)}] {c} FAIL")
        else:
            try:
                (HIST_DIR/f"{c}.json").write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
                ok+=1
                if i%20==0: print(f"[{i}/{len(target)}] {c} OK {len(bars)} ok={ok} fail={fail}")
            except:
                fail+=1
        time.sleep(0.25)  # 250ms，慢一点，不被踢

    meta={"updated":datetime.datetime.now().isoformat(),"count":len(codes),"shard":f"{shard}/{total_shards}","range":f"{s}-{e}","ok":ok,"fail":fail,"saved_total":len(list(HIST_DIR.glob("*.json"))),"cleaned_fake":cleaned,"v":"V5.9 清理假数据+重试版","note":"已清理假数据，东财重试3次，间隔250ms，断档前端补齐；COST/ZQ/ZQ1全部参与今日"}
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)

if __name__=="__main__":
    main()
