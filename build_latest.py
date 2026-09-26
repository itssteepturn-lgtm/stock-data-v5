"""
V5全功能版 - build_latest.py 纯东财版
- 全部东财，不混 baostock
- 历史：push2his 150天 f56量手*100 f57额 f61换手
- 均价 avg = 额/量股
- 换手 turn = f61/100 上限100%
- GRID=300 三角峰值在avg dist*=(1-turn)
"""
import os, json, time, random, traceback
from datetime import datetime
import requests

GRID=300
HIST_DAYS=150
RETRY=2
SLEEP=0.8
TEST_STOCKS=["300313","600519","600127","003006","002909","920706","688137"]
UA_LIST=[
"Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def to_secid(code):
    code=str(code).zfill(6)
    return (f"1.{code}", f"sh_{code}.json") if code.startswith('6') else (f"0.{code}", f"sz_{code}.json")

def build_chip(bars):
    n=len(bars)
    if n==0: return None
    minP=min(b['low'] for b in bars); maxP=max(b['high'] for b in bars)
    if maxP<=minP: maxP=minP*1.1
    step=(maxP-minP)/GRID
    if step<=0: step=maxP*0.001 or 0.01
    dist=[0.0]*GRID
    cost50=[0]*n; cost75=[0]*n; cost90=[0]*n; zq=[0]*n; zq1=[0]*n; vwma=[0]*n
    for i in range(n):
        sCV=sV=0.0
        for k in range(max(0,i-9), i+1):
            sCV+=bars[k]['close']*bars[k]['volume']; sV+=bars[k]['volume']
        vwma[i]=sCV/sV if sV else bars[i]['close']
    for i in range(n):
        b=bars[i]
        turn=max(0.0001, min(b.get('turn',0.01), 1.0))
        for g in range(GRID): dist[g]*=(1.0-turn)
        low=b['low']; high=b['high']; avg=b.get('avg', b['close'])
        def p2i(p): return max(0, min(GRID-1, int((p-minP)/step)))
        lowIdx=p2i(low); highIdx=p2i(high); avgIdx=p2i(avg)
        if lowIdx>highIdx: lowIdx,highIdx=highIdx,lowIdx
        avgIdx=max(lowIdx, min(highIdx, avgIdx))
        weights=[]; idxs=[]
        for g in range(lowIdx, highIdx+1):
            idxs.append(g)
            if highIdx==lowIdx: w=1.0
            else:
                if g<=avgIdx: w=(g-lowIdx)/((avgIdx-lowIdx) or 1)
                else: w=(highIdx-g)/((highIdx-avgIdx) or 1)
            weights.append(max(0.0,w))
        if sum(weights)==0: weights=[1.0]*len(idxs)
        sumW=sum(weights) or 1.0
        for j,g in enumerate(idxs): dist[g]+=weights[j]/sumW*turn
        total=sum(dist) or 1.0
        cum=0.0; c50=c75=c90=0.0
        for g in range(GRID):
            cum+=dist[g]; ratio=cum/total; price=minP+g*step
            if not c50 and ratio>=0.5: c50=price
            if not c75 and ratio>=0.75: c75=price
            if not c90 and ratio>=0.9: c90=price
        cost50[i]=c50 or b['close']; cost75[i]=c75 or b['close']; cost90[i]=c90 or b['close']
        def winner(price):
            win=0.0
            for g in range(GRID):
                if minP+g*step<=price: win+=dist[g]
            return win/total*100.0
        zq[i]=winner(b.get('avg', b['close'])); zq1[i]=winner(vwma[i])
    return dict(cost50=cost50,cost75=cost75,cost90=cost90,zq=zq,zq1=zq1,vwma=vwma,minP=minP,maxP=maxP,dist=dist)

def fetch_eastmoney_history(code):
    secid,_=to_secid(code)
    url="https://push2his.eastmoney.com/api/qt/stock/kline/get"
    for fields in ["f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63","f51,f52,f53,f54,f55,f56,f57,f58,f62,f63"]:
        params={"secid":secid,"klt":"101","fqt":"1","lmt":str(HIST_DAYS+20),"fields2":fields,"ut":"fa5fd1943c7b386f172d6893dbfba10b"}
        for attempt in range(RETRY+1):
            try:
                headers={"User-Agent":random.choice(UA_LIST),"Referer":"https://quote.eastmoney.com/"}
                r=requests.get(url, params=params, headers=headers, timeout=12)
                j=r.json(); klines=j.get('data',{}).get('klines',[])
                if not klines: time.sleep(SLEEP); continue
                bars=[]
                for line in klines:
                    a=line.split(',')
                    try:
                        d=a[0]; o=float(a[1]); c=float(a[2]); h=float(a[3]); l=float(a[4])
                        vol_hand=float(a[5]); amount=float(a[6]); turn=0.01
                        for idx in [10,9,8,11,12]:
                            if idx < len(a):
                                try:
                                    v=float(a[idx])
                                    if 0 <= v <= 100: turn=v/100.0
                                except: pass
                        vol_share=vol_hand*100.0
                        avg=amount/vol_share if vol_share else (o+h+l+c)/4.0
                        if vol_share==0: continue
                        bars.append(dict(date=d, open=o, high=h, low=l, close=c, volume=vol_share, amount=amount, turn=turn, avg=avg))
                    except: continue
                bars=bars[-HIST_DAYS:]
                if len(bars)>=30: return bars
            except Exception as e:
                print(f"  {code} history attempt {attempt} err {e}"); time.sleep(SLEEP*2)
        time.sleep(SLEEP)
    return []

def save_stock(code, bars, chip):
    _, fname=to_secid(code)
    os.makedirs("data/stocks", exist_ok=True)
    out_bars=[]
    for i,b in enumerate(bars):
        out_bars.append(dict(d=b['date'], o=round(b['open'],3), h=round(b['high'],3), l=round(b['low'],3), c=round(b['close'],3), v=b['volume'], a=b['amount'], turn=round(b['turn'],6), avg=round(b['avg'],3), cost50=round(chip['cost50'][i],3), cost75=round(chip['cost75'][i],3), cost90=round(chip['cost90'][i],3), zq=round(chip['zq'][i],2), zq1=round(chip['zq1'][i],2), vwma=round(chip['vwma'][i],3)))
    out=dict(code=code, secid=to_secid(code)[0], minP=chip['minP'], maxP=chip['maxP'], dist=chip['dist'], bars=out_bars, updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), count=len(out_bars), source="eastmoney f56*100 f57 f61")
    path=f"data/stocks/{fname}"
    with open(path,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False)
    print(f"  saved {path} last {out_bars[-1]['c']} COST {out_bars[-1]['cost50']}/{out_bars[-1]['cost75']}/{out_bars[-1]['cost90']} ZQ {out_bars[-1]['zq']}")
    return out

def main():
    codes=TEST_STOCKS
    env=os.getenv("STOCK_CODES")
    if env: codes=[c.strip() for c in env.split(",") if c.strip()]
    clean=os.getenv("CLEAN","false").lower()=="true"
    if clean:
        import shutil
        if os.path.exists("data/stocks"): shutil.rmtree("data/stocks")
    os.makedirs("data/stocks", exist_ok=True); os.makedirs("data/indices", exist_ok=True); os.makedirs("data", exist_ok=True)
    existing=set()
    if not clean and os.path.exists("data/stocks"):
        for fn in os.listdir("data/stocks"): m=fn.split('_')[-1].split('.')[0]; existing.add(m)
    all_ok=[]; failed=[]
    for code in codes:
        if code in existing:
            print(f"== {code} 已存在跳过")
            try:
                _, fname=to_secid(code)
                with open(f"data/stocks/{fname}","r",encoding="utf-8") as f: j=json.load(f); all_ok.append(dict(code=code, last=j['bars'][-1])); continue
            except: pass
        print(f"\n== {code} 东财抓取 ==")
        for attempt in range(RETRY+1):
            try:
                bars=fetch_eastmoney_history(code)
                if not bars or len(bars)<30: raise ValueError(f"bars {len(bars)}")
                chip=build_chip(bars)
                saved=save_stock(code,bars,chip)
                all_ok.append(dict(code=code, last=saved['bars'][-1])); break
            except Exception as e:
                print(f"  fail {e}"); traceback.print_exc()
                if attempt<RETRY: time.sleep(SLEEP*2)
                else: failed.append(code)
        time.sleep(SLEEP)
    meta=dict(total=len(all_ok), failed=failed, updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), grid=GRID, hist_days=HIST_DAYS, method="eastmoney pure f56*100 f57 f61 triangle decay 300", stocks=[a['code'] for a in all_ok])
    with open("data/meta.json","w",encoding="utf-8") as f: json.dump(meta,f,ensure_ascii=False,indent=2)
    steep=[]
    for a in all_ok:
        last=a['last']
        steep.append(dict(code=a['code'], c=last['c'], cost50=last['cost50'], cost75=last['cost75'], cost90=last['cost90'], zq=last['zq'], zq1=last['zq1'], turn=last['turn']))
    with open("data/steep_all.json","w",encoding="utf-8") as f: json.dump(dict(updated=meta['updated'], data=steep), f, ensure_ascii=False, indent=2)
    print(f"\nDone ok={len(all_ok)} failed={failed}")

if __name__=="__main__": main()
