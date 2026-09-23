import json, pathlib, requests, time, datetime

DATA_DIR = pathlib.Path("data")
HIST_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

def secid(code):
    code=str(code).zfill(6)
    if code.startswith('6'): return f'1.{code}'
    if code.startswith('0') or code.startswith('3'): return f'0.{code}'
    if code.startswith('8') or code.startswith('4') or code.startswith('92'): return f'0.{code}'
    return f'1.{code}'

def fetch_codes():
    url="https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5500&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12,f14"
    try:
        r=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla'}).json()
        diff=r['data']['diff']
        codes=[d['f12'] for d in diff if d['f12']]
        print(f"fetch codes {len(codes)}")
        return codes
    except Exception as e:
        print("codes fail",e)
        return ["000001","600519","000858","300750","300313"]

def fetch_kline(code):
    sid=secid(code)
    url=f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&secid={sid}&beg=0&end=20500101&lmt=360"
    try:
        r=requests.get(url,timeout=10,headers={'User-Agent':'Mozilla'}).json()
        if 'data' not in r or not r['data'] or 'klines' not in r['data']: return []
        klines=r['data']['klines']
        bars=[]
        for line in klines:
            p=line.split(',')
            # f51 date, f52 open, f53 close, f54 high, f55 low, f57 vol, f58 amount
            bars.append({
                "d":p[0],
                "o":float(p[1]),
                "c":float(p[2]),
                "h":float(p[3]),
                "l":float(p[4]),
                "v":float(p[5]),
                "a":float(p[6]),
            })
        return bars
    except Exception as e:
        print(f"kline {code} fail {e}")
        return []

def main():
    codes=fetch_codes()
    (DATA_DIR/"codes.json").write_text(json.dumps(codes,ensure_ascii=False),encoding='utf-8')
    # Actions 6分钟超时保护，分批：首次跑前2500，够手机用
    limit=2500
    for idx,c in enumerate(codes[:limit]):
        bars=fetch_kline(c)
        if len(bars)>=40:
            (HIST_DIR/f"{c}.json").write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
        if idx%100==0:
            print(f"{idx}/{limit} {c} {len(bars)}")
        time.sleep(0.05)
    meta={"updated":datetime.datetime.now().isoformat(),"count":len(codes),"saved":min(len(codes),limit),"v":"V5自养版-东财K线","note":"自养数据：养在Actions，读自家data，临时东财，备份在GitHub"}
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print("done",meta)

if __name__=="__main__":
    main()
