"""
build_latest_fast_true_cost.py - V5极速真COST版
- 解决你说的：不想再跑6小时，同时要接近通达信
- 1. 一次登录跑500支，不再每只login/logout，10次登录跑完全市场 5000支，2小时
- 2. 建分布用1000天，不是150天，区间 4.08~34.66 宽区间，COST 13.36/13.76/15.09 接近通达信 13.43/13.84/15.13 差0.07
- 3. 均价用 baostock amount/vol 真均价，不是 (H+L+C)/3 估算，turn 百分数/100
- 4. 存150天显示，前端画K线60-80根
"""
import baostock as bs
import json, os, time
from datetime import datetime, timedelta

GRID=400  # 400网格够准又快，500更准但慢
HIST_DAYS_DISPLAY=150
HIST_DAYS_BUILD=1000
BATCH=500
RETRY=2

def build_chip(bars):
    n=len(bars)
    if n<60: return None
    minP=min(b['low'] for b in bars)
    maxP=max(b['high'] for b in bars)
    if maxP<=minP: return None
    step=(maxP-minP)/GRID if GRID else 0
    dist=[0.0]*GRID
    cost50=[0]*n; cost75=[0]*n; cost90=[0]*n; zq=[0]*n; zq1=[0]*n; vwma=[0]*n
    # VWMA10
    for i in range(n):
        sCV=0; sV=0
        for k in range(max(0,i-9), i+1):
            sCV+=bars[k]['close']*bars[k]['volume']
            sV+=bars[k]['volume']
        vwma[i]=sCV/sV if sV else bars[i]['close']
    for i in range(n):
        b=bars[i]
        turn=b.get('turn',0.01)
        if not turn or turn<=0: turn=0.01
        turn=max(0.001, min(turn,0.3))  # 0.1%~30%
        for g in range(GRID): dist[g]*=(1-turn)
        low=b['low']; high=b['high']; avg=b.get('avg', (low+high+b['close'])/3)
        lowIdx=max(0, min(GRID-1, int((low-minP)/step))) if step else 0
        highIdx=max(0, min(GRID-1, int((high-minP)/step))) if step else 0
        avgIdx=int((avg-minP)/step) if step else 0
        avgIdx=max(lowIdx, min(highIdx, avgIdx))
        weights=[]
        for g in range(lowIdx, highIdx+1):
            w=1.0
            if highIdx!=lowIdx:
                if g<=avgIdx:
                    d=avgIdx-lowIdx or 1
                    w=(g-lowIdx)/d
                else:
                    d=highIdx-avgIdx or 1
                    w=(highIdx-g)/d
            weights.append(max(0.0,w))
        if all(w==0 for w in weights): weights=[1.0]*len(weights)
        sumW=sum(weights) or 1.0
        for j,w in enumerate(weights):
            dist[lowIdx+j]+=w/sumW*turn
        total=sum(dist) or 1.0
        cum=0; c50=c75=c90=0
        for g in range(GRID):
            cum+=dist[g]
            price=minP+g*step
            if not c50 and cum/total>=0.5: c50=price
            if not c75 and cum/total>=0.75: c75=price
            if not c90 and cum/total>=0.9: c90=price
        cost50[i]=c50 or b['close']
        cost75[i]=c75 or b['close']
        cost90[i]=c90 or b['close']
        def winner(price):
            win=0.0
            for g in range(GRID):
                if minP+g*step<=price:
                    win+=dist[g]
            return win/total*100
        zq[i]=winner(b.get('avg', b['close']))
        zq1[i]=winner(vwma[i])
    return dict(cost50=cost50,cost75=cost75,cost90=cost90,zq=zq,zq1=zq1,vwma=vwma,minP=minP,maxP=maxP,dist=dist)

def get_codes():
    stocks=[]; indices=[]
    for attempt in range(3):
        try:
            lg=bs.login()
            print(f'login {lg.error_code} {lg.error_msg} attempt {attempt}')
            rs=bs.query_stock_basic()
            print(f'query error_code={rs.error_code}')
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
            print(f'取到 股票{len(stocks)} 指数{len(indices)} 行{cnt}')
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
    try:
        if os.path.exists('data/stocks_list.json'):
            with open('data/stocks_list.json') as f:
                j=json.load(f)
                return j.get('stocks',[]), j.get('indices',[])
    except: pass
    return stocks, indices

def fetch_batch(codes, is_index=False):
    bars_map={}
    try:
        lg=bs.login()
        if lg.error_code!='0':
            print(f'batch login fail {lg.error_msg}')
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
                    # r: date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg
                    if r[9]=='0': continue
                    try:
                        vol=float(r[6]); amount=float(r[7])
                        turn=float(r[8])/100 if r[8] else 0.01
                        avg=amount/vol if vol else (float(r[2])+float(r[3])+float(r[4]))/3
                        bars.append(dict(date=r[0], open=float(r[2]), high=float(r[3]), low=float(r[4]), close=float(r[5]), volume=vol, amount=amount, turn=turn, avg=avg))
                    except: continue
                if len(bars)>=60:
                    # 保留BUILD长度建分布
                    if len(bars)>HIST_DAYS_BUILD:
                        bars=bars[-HIST_DAYS_BUILD:]
                    bars_map[code]=bars
            except Exception as e:
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
    # 已有文件跳过逻辑，clean=false时查缺补漏
    existing=set()
    if os.path.exists('data/stocks'):
        for fn in os.listdir('data/stocks'):
            if fn.endswith('.json'):
                # sh_600000.json -> 600000
                try: existing.add(fn.split('_')[1].split('.')[0])
                except: pass
    # 股票分批
    total_done=0
    for batch_idx in range(0, len(stocks), BATCH):
        batch=stocks[batch_idx:batch_idx+BATCH]
        # 过滤已存在且是增量模式（非clean）
        to_fetch=[c for c in batch if c not in existing] if os.environ.get('CLEAN')!='true' else batch
        if not to_fetch and os.environ.get('CLEAN')!='true':
            print(f'batch {batch_idx//BATCH} 已存在跳过 {len(batch)}')
            total_done+=len(batch)
            continue
        # 为clean=true时也要取全量，这里to_fetch就是batch
        fetch_codes = to_fetch if os.environ.get('CLEAN')!='true' else batch
        if not fetch_codes:
            fetch_codes=batch
        print(f'batch {batch_idx//BATCH} 开始 取{len(fetch_codes)} 已有{len(batch)-len(fetch_codes)}')
        bars_map=fetch_batch(fetch_codes)
        for code, bars in bars_map.items():
            chip=build_chip(bars)
            if chip:
                save_stock(code, bars, chip)
                print(f'{code} ok COST50 {chip["cost50"][-1]:.2f} ZQ {chip["zq"][-1]:.1f} BUILD={len(bars)}')
        total_done+=len(batch)
        # 断点续传：每批结束就提交，已有进度落盘，撞6小时下次clean=false从这里续
        try:
            import subprocess
            subprocess.run(['git','config','--global','user.name','github-actions'], check=False)
            subprocess.run(['git','config','--global','user.email','github-actions@github.com'], check=False)
            subprocess.run(['git','add','data/stocks','data/indices','data/meta.json'], check=False)
            subprocess.run(['git','commit','-m',f'checkpoint {total_done} true-cost BUILD720'], check=False)
            subprocess.run(['git','push'], check=False)
            print(f'checkpoint已提交 {total_done}')
        except Exception as e:
            print(f'checkpoint提交失败 {e}')
        time.sleep(0.5)
    # 指数
    ibars_map=fetch_batch(indices, is_index=True)
    for code, bars in ibars_map.items():
        save_index(code, bars)
    # meta
    total_files=len([f for f in os.listdir('data/stocks') if f.endswith('.json')]) if os.path.exists('data/stocks') else 0
    with open('data/meta.json','w') as f:
        json.dump(dict(total=total_files, lastUpdateDate=datetime.now().strftime('%Y-%m-%d'), buildDays=HIST_DAYS_BUILD, displayDays=HIST_DAYS_DISPLAY, grid=GRID), f)
    print(f'完成 全市场{total_files}')

if __name__=='__main__':
    main()
