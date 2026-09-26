
import baostock as bs
import json, os, sys, time
from datetime import datetime, timedelta
import numpy as np

GRID=400
HIST_BUILD=150
HIST_DISPLAY=150
BATCH_COMMIT=500

def build_chip(bars):
    n=len(bars)
    if n<60: return None
    lows=np.array([b['low'] for b in bars])
    highs=np.array([b['high'] for b in bars])
    closes=np.array([b['close'] for b in bars])
    avgs=np.array([b['avg'] for b in bars])
    turns=np.array([b['turn'] for b in bars])
    vols=np.array([b['volume'] for b in bars])
    minP=float(np.min(lows)); maxP=float(np.max(highs))
    if maxP<=minP: return None
    step=(maxP-minP)/GRID
    dist=np.zeros(GRID)
    cost50=np.zeros(n); cost75=np.zeros(n); cost90=np.zeros(n)
    zq=np.zeros(n); zq1=np.zeros(n); vwma=np.zeros(n)
    price_grid = minP + np.arange(GRID)*step
    for i in range(n):
        s=max(0,i-9)
        cv=np.sum(closes[s:i+1]*vols[s:i+1]); sv=np.sum(vols[s:i+1])
        vwma[i]=cv/sv if sv else closes[i]
    for i in range(n):
        turn=float(turns[i])
        if not turn: turn=0.001
        turn=max(0.0001, min(turn,0.3))
        dist*=(1-turn)
        low=lows[i]; high=highs[i]; avg=avgs[i]
        lowIdx=int((low-minP)/step); highIdx=int((high-minP)/step); avgIdx=int((avg-minP)/step)
        lowIdx=max(0,min(GRID-1,lowIdx)); highIdx=max(0,min(GRID-1,highIdx)); avgIdx=max(lowIdx,min(highIdx,avgIdx))
        if lowIdx>highIdx: lowIdx,highIdx=highIdx,lowIdx
        size=highIdx-lowIdx+1
        if size<=0: continue
        weights=np.zeros(size)
        dl=avgIdx-lowIdx; dr=highIdx-avgIdx
        for j in range(size):
            g=lowIdx+j
            if g<=avgIdx:
                w=1.0 if dl==0 and g==avgIdx else (g-lowIdx)/dl if dl else 0
            else:
                w=1.0 if dr==0 and g==avgIdx else (highIdx-g)/dr if dr else 0
            weights[j]=max(0,w)
        if np.all(weights==0): weights[:]=1.0
        sW=np.sum(weights)
        if sW>0: dist[lowIdx:highIdx+1]+=weights/sW*turn
        total=np.sum(dist)
        if total<=0:
            cost50[i]=closes[i]; cost75[i]=closes[i]; cost90[i]=closes[i]
            continue
        cumsum=np.cumsum(dist); ratio=cumsum/total
        cost50[i]=price_grid[np.searchsorted(ratio,0.5)] if np.searchsorted(ratio,0.5)<GRID else closes[i]
        cost75[i]=price_grid[np.searchsorted(ratio,0.75)] if np.searchsorted(ratio,0.75)<GRID else closes[i]
        cost90[i]=price_grid[np.searchsorted(ratio,0.9)] if np.searchsorted(ratio,0.9)<GRID else closes[i]
        idx_c=int((closes[i]-minP)/step); idx_a=int((avgs[i]-minP)/step)
        idx_c=max(0,min(GRID-1,idx_c)); idx_a=max(0,min(GRID-1,idx_a))
        zq[i]=np.sum(dist[:idx_c+1])/total*100
        zq1[i]=np.sum(dist[:idx_a+1])/total*100
    return dict(cost50=cost50.tolist(), cost75=cost75.tolist(), cost90=cost90.tolist(), zq=zq.tolist(), zq1=zq1.tolist(), vwma=vwma.tolist(), minP=minP, maxP=maxP, dist=dist.tolist())

def get_all_codes():
    codes=[]
    try:
        lg=bs.login()
        print(f"login all_stock: {lg.error_code} {lg.error_msg}")
        # 今天可能是非交易日，往前找5天
        for offset in range(0, 7):
            day = (datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d')
            rs=bs.query_all_stock(day=day)
            print(f"query_all_stock {day}: {rs.error_code} {rs.error_msg}")
            if rs.error_code=='0':
                while rs.next():
                    row=rs.get_row_data()
                    codes.append(row[0].split('.')[1])
                if codes:
                    print(f"get_all_codes from {day} got {len(codes)}")
                    break
        bs.logout()
    except Exception as e:
        print(f"get_all_codes exception {e}")
        try: bs.logout()
        except: pass
    if not codes:
        print("get_all_codes 为空，用你给的7只保底调试")
        codes = ["688137","920706","002909","003086","600127","600519","300313"]
    return sorted(set(codes))

def fetch_one(code):
    bars=[]
    lg=bs.login()
    if lg.error_code!='0': return []
    fields='date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg'
    start_date=(datetime.now()-timedelta(days=HIST_BUILD+120)).strftime('%Y-%m-%d')
    end_date=datetime.now().strftime('%Y-%m-%d')
    sec=f"sh.{code}" if (code.startswith('6') or code.startswith('9') or code.startswith('688')) else f"sz.{code}"
    if code=='000001': sec='sh.000001'
    rs=bs.query_history_k_data_plus(sec, fields, start_date=start_date, end_date=end_date, frequency='d', adjustflag='2')
    lst=[]
    if rs.error_code=='0':
        while rs.error_code=='0' and rs.next():
            lst.append(rs.get_row_data())
    for r in lst:
        if r[9]=='0': continue
        try:
            vol=float(r[6]); amount=float(r[7]); turn=float(r[8])/100 if r[8] else 0.001
            avg=amount/vol if vol else float(r[5])
            bars.append(dict(date=r[0], open=float(r[2]), high=float(r[3]), low=float(r[4]), close=float(r[5]), volume=vol, amount=amount, turn=turn, avg=avg))
        except: continue
    bs.logout()
    if len(bars)>HIST_BUILD: bars=bars[-HIST_BUILD:]
    return bars

if __name__ == "__main__":
    clean = '--clean' in sys.argv
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data', 'stocks')
    if clean and os.path.exists(data_dir):
        import shutil
        print(f"clean 删除 {data_dir}")
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    print(f"data目录 {data_dir} 已创建 exists={os.path.exists(data_dir)}")
    codes = get_all_codes()
    print(f"Total {len(codes)} -> {codes[:20]}")
    cnt=0
    for code in codes:
        try:
            bars=fetch_one(code)
            if len(bars)<60:
                print(f"{code} skip bars {len(bars)}")
                continue
            chip=build_chip(bars)
            if not chip:
                print(f"{code} chip None")
                continue
            display=bars[-HIST_DISPLAY:]
            offset=len(bars)-len(display)
            out=[]
            for j,b in enumerate(display):
                i=offset+j
                out.append(dict(d=b['date'], o=b['open'], c=b['close'], h=b['high'], l=b['low'], v=b['volume'], a=b['amount'], turn=b['turn'], avg=b['avg'], cost50=chip['cost50'][i], cost75=chip['cost75'][i], cost90=chip['cost90'][i], zq=chip['zq'][i], zq1=chip['zq1'][i], vwma=chip['vwma'][i]))
            pref='sh' if (code.startswith('6') or code.startswith('9') or code.startswith('688')) else 'sz'
            out_path = os.path.join(data_dir, f'{pref}_{code}.json')
            with open(out_path,'w') as f:
                json.dump(dict(bars=out, dist=chip['dist'], minP=chip['minP'], maxP=chip['maxP'], updated=datetime.now().isoformat(), buildDays=len(bars)), f)
            cnt+=1
            print(f"{cnt} {code} OK COST50 {out[-1]['cost50']:.2f} COST75 {out[-1]['cost75']:.2f} ZQ {out[-1]['zq']:.1f} 文件 {out_path}")
            if cnt%100==0:
                print(f"{cnt} {code} COST50 {out[-1]['cost50']:.2f}")
        except Exception as e:
            import traceback
            print(f"{code} error {e}")
            traceback.print_exc()
            continue
    print(f"DONE {cnt} 文件夹 {data_dir} 文件数 {len(os.listdir(data_dir)) if os.path.exists(data_dir) else 0}")
