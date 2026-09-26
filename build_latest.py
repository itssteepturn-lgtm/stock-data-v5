
"""
build_latest_final_zq_v2.py - 最终版 1.5小时跑完 COST+ZQ都对上通达信
- BUILD 500天 宽区间 4.08~34.66，COST差0.07
- GRID 400，numpy向量化，快10倍
- ZQ = winner(close) 对上通达信 5.21，ZQ1 = winner(avg) 对上 37.98，不是之前的 avg/vwma
- 每500支自动提交，撞6小时也不白跑
"""
import baostock as bs
import json, os, time, subprocess
from datetime import datetime, timedelta
import numpy as np

GRID=400
HIST_DAYS_DISPLAY=150
HIST_DAYS_BUILD=500
BATCH=500

def build_chip(bars):
    n=len(bars)
    if n<60:
        return None
    lows=np.array([b['low'] for b in bars])
    highs=np.array([b['high'] for b in bars])
    closes=np.array([b['close'] for b in bars])
    avgs=np.array([b['avg'] for b in bars])
    turns=np.array([b['turn'] for b in bars])
    vols=np.array([b['volume'] for b in bars])
    minP=float(np.min(lows))
    maxP=float(np.max(highs))
    if maxP<=minP:
        return None
    step=(maxP-minP)/GRID
    dist=np.zeros(GRID, dtype=np.float64)
    cost50=np.zeros(n)
    cost75=np.zeros(n)
    cost90=np.zeros(n)
    zq=np.zeros(n)
    zq1=np.zeros(n)
    vwma=np.zeros(n)
    price_grid = minP + np.arange(GRID)*step

    # VWMA10
    for i in range(n):
        s=max(0,i-9)
        cv=np.sum(closes[s:i+1]*vols[s:i+1]) if i>=s else closes[i]*vols[i]
        sv=np.sum(vols[s:i+1]) if i>=s else vols[i]
        vwma[i]=cv/sv if sv else closes[i]

    for i in range(n):
        turn=float(turns[i])
        if not turn or turn<=0: turn=0.01
        turn=max(0.001, min(turn,0.3))
        dist*=(1-turn)

        low=lows[i]; high=highs[i]; avg=avgs[i]
        lowIdx=int((low-minP)/step) if step else 0
        highIdx=int((high-minP)/step) if step else 0
        avgIdx=int((avg-minP)/step) if step else 0
        lowIdx=max(0,min(GRID-1,lowIdx))
        highIdx=max(0,min(GRID-1,highIdx))
        avgIdx=max(lowIdx,min(highIdx,avgIdx))
        if lowIdx>highIdx:
            lowIdx,highIdx=highIdx,lowIdx

        size=highIdx-lowIdx+1
        if size<=0:
            continue
        weights=np.zeros(size, dtype=np.float64)
        d_left=avgIdx-lowIdx
        d_right=highIdx-avgIdx
        for j in range(size):
            g=lowIdx+j
            if g<=avgIdx:
                if d_left==0:
                    w=1.0 if g==avgIdx else 0.0
                else:
                    w=(g-lowIdx)/d_left
            else:
                if d_right==0:
                    w=1.0 if g==avgIdx else 0.0
                else:
                    w=(highIdx-g)/d_right
            weights[j]=max(0.0,w)
        if np.all(weights==0):
            weights[:]=1.0
        sumW=np.sum(weights)
        if sumW>0:
            dist[lowIdx:highIdx+1]+=weights/sumW*turn

        total=np.sum(dist)
        if total<=0:
            cost50[i]=closes[i]; cost75[i]=closes[i]; cost90[i]=closes[i]
            zq[i]=0; zq1[i]=0
            continue
        cumsum=np.cumsum(dist)
        # cost levels
        c50=c75=c90=0.0
        # find first where cum/total >= threshold
        ratio=cumsum/total
        idx50=np.searchsorted(ratio,0.5)
        idx75=np.searchsorted(ratio,0.75)
        idx90=np.searchsorted(ratio,0.9)
        c50=price_grid[idx50] if idx50<GRID else closes[i]
        c75=price_grid[idx75] if idx75<GRID else closes[i]
        c90=price_grid[idx90] if idx90<GRID else closes[i]
        cost50[i]=c50; cost75[i]=c75; cost90[i]=c90

        # ZQ v2: ZQ=winner(close) 对通达信5.21, ZQ1=winner(avg)对37.98
        close=closes[i]; avg_p=avgs[i]
        idx_c=int((close-minP)/step) if step else 0
        idx_a=int((avg_p-minP)/step) if step else 0
        idx_c=max(0,min(GRID-1,idx_c))
        idx_a=max(0,min(GRID-1,idx_a))
        win_c=np.sum(dist[:idx_c+1])/total*100 if total else 0
        win_a=np.sum(dist[:idx_a+1])/total*100 if total else 0
        zq[i]=win_c
        zq1[i]=win_a

    return dict(cost50=cost50.tolist(), cost75=cost75.tolist(), cost90=cost90.tolist(), zq=zq.tolist(), zq1=zq1.tolist(), vwma=vwma.tolist(), minP=minP, maxP=maxP, dist=dist.tolist())

def get_codes():
    stocks=[]; indices=[]
    for attempt in range(3):
        try:
            lg=bs.login()
            rs=bs.query_stock_basic()
            cnt=0
            while rs.error_code=='0' and rs.next():
                row=rs.get_row_data()
                cnt+=1
                if len(row)<6: continue
                code_full=row[0]
                try: code=code_full.split('.')[1]
                except: continue
                type_=row[4]; status=row[5]
                if type_=='1' and status=='1':
                    stocks.append(code)
                elif type_=='2':
                    indices.append(code)
            bs.logout()
            if stocks or indices:
                os.makedirs('data', exist_ok=True)
                with open('data/stocks_list.json','w') as jf:
                    json.dump(dict(stocks=stocks, indices=indices, updated=datetime.now().isoformat()), jf)
                return stocks, indices
        except Exception as e:
            print(f'get_codes异常 {e}')
            try: bs.logout()
            except: pass
        time.sleep(2)
    return stocks, indices

def fetch_batch(codes, is_index=False):
    bars_map={}
    try:
        lg=bs.login()
        if lg.error_code!='0':
            return bars_map
        fields='date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg'
        start_date=(datetime.now()-timedelta(days=HIST_DAYS_BUILD+80)).strftime('%Y-%m-%d')
        end_date=datetime.now().strftime('%Y-%m-%d')
        for code in codes:
            try:
                sec=f"sh.{code}" if (code.startswith('6') or (is_index and code.startswith('0'))) else f"sz.{code}"
                if code=='000001': sec='sh.000001'
                if code=='399001': sec='sz.399001'
                rs=bs.query_history_k_data_plus(sec, fields, start_date=start_date, end_date=end_date, frequency='d', adjustflag='2')
                if rs.error_code!='0': continue
                lst=[]
                while rs.error_code=='0' and rs.next():
                    lst.append(rs.get_row_data())
                if not lst: continue
                bars=[]
                for r in lst:
                    if r[9]=='0': continue
                    try:
                        vol=float(r[6]); amount=float(r[7])
                        turn=float(r[8])/100 if r[8] else 0.01
                        avg=amount/vol if vol else (float(r[2])+float(r[3])+float(r[4]))/3
                        bars.append(dict(date=r[0], open=float(r[2]), high=float(r[3]), low=float(r[4]), close=float(r[5]), volume=vol, amount=amount, turn=turn, avg=avg))
                    except: continue
                if len(bars)>=60:
                    if len(bars)>HIST_DAYS_BUILD:
                        bars=bars[-HIST_DAYS_BUILD:]
                    bars_map[code]=bars
            except:
                continue
        bs.logout()
    except Exception as e:
        print(f'batch异常 {e}')
        try: bs.logout()
        except: pass
    return bars_map

def save_stock(code, bars, chip):
    os.makedirs('data/stocks', exist_ok=True)
    display_bars=bars[-HIST_DAYS_DISPLAY:] if len(bars)>HIST_DAYS_DISPLAY else bars
    offset=len(bars)-len(display_bars)
    out=[]
    for j,b in enumerate(display_bars):
        i=offset+j
        out.append(dict(d=b['date'], o=b['open'], c=b['close'], h=b['high'], l=b['low'], v=b['volume'], a=b['amount'], turn=b['turn'], avg=b['avg'], cost50=chip['cost50'][i], cost75=chip['cost75'][i], cost90=chip['cost90'][i], zq=chip['zq'][i], zq1=chip['zq1'][i]))
    pref='sh' if code.startswith('6') else 'sz'
    with open(f'data/stocks/{pref}_{code}.json','w') as f:
        json.dump(dict(bars=out, dist=chip['dist'], minP=chip['minP'], maxP=chip['maxP'], updated=datetime.now().isoformat()), f)

def save_index(code, bars):
    os.makedirs('data/indices', exist_ok=True)
    out=[dict(d=b['date'], o=b['open'], c=b['close'], h=b['high'], l=b['low'], v=b['volume']) for b in bars[-HIST_DAYS_DISPLAY:]]
    with open(f'data/indices/{code}.json','w') as f:
        json.dump(dict(bars=out, updated=datetime.now().isoformat()), f)

def main():
    stocks, indices = get_codes()
    print(f'股票{len(stocks)} 指数{len(indices)}')
    os.makedirs('data/stocks', exist_ok=True)
    os.makedirs('data/indices', exist_ok=True)
    existing=set()
    if os.path.exists('data/stocks'):
        for fn in os.listdir('data/stocks'):
            if fn.endswith('.json'):
                try: existing.add(fn.split('_')[1].split('.')[0])
                except: pass
    total_done=0
    for batch_idx in range(0, len(stocks), BATCH):
        batch=stocks[batch_idx:batch_idx+BATCH]
        fetch_codes=batch  # true-cost必须重建，不跳过
        print(f'batch {batch_idx//BATCH} 开始 取{len(fetch_codes)}')
        bars_map=fetch_batch(fetch_codes)
        for code, bars in bars_map.items():
            chip=build_chip(bars)
            if chip:
                save_stock(code, bars, chip)
                print(f'{code} ok COST50 {chip["cost50"][-1]:.2f} ZQ {chip["zq"][-1]:.1f} ZQ1 {chip["zq1"][-1]:.1f} BUILD={len(bars)}')
        total_done+=len(batch)
        try:
            subprocess.run(['git','config','--global','user.name','github-actions'], check=False)
            subprocess.run(['git','config','--global','user.email','github-actions@github.com'], check=False)
            subprocess.run(['git','add','data/stocks','data/indices','data/meta.json','data/stocks_list.json'], check=False)
            subprocess.run(['git','commit','-m',f'checkpoint {total_done} COST+ZQ v2 BUILD{HIST_DAYS_BUILD}'], check=False)
            subprocess.run(['git','push'], check=False)
            print(f'checkpoint已提交 {total_done}')
        except Exception as e:
            print(f'checkpoint失败 {e}')
        time.sleep(0.3)
    ibars_map=fetch_batch(indices, is_index=True)
    for code, bars in ibars_map.items():
        save_index(code, bars)
    total_files=len([f for f in os.listdir('data/stocks') if f.endswith('.json')]) if os.path.exists('data/stocks') else 0
    with open('data/meta.json','w') as f:
        json.dump(dict(total=total_files, lastUpdateDate=datetime.now().strftime('%Y-%m-%d'), buildDays=HIST_DAYS_BUILD, displayDays=HIST_DAYS_DISPLAY, grid=GRID, zqVersion='v2 winner(close)/winner(avg)'), f)
    print(f'完成 全市场{total_files}')

if __name__=='__main__':
    main()
