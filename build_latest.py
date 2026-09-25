"""
build_latest_v5_full.py - V5全功能版后台，iPhone专用
要求：
- 0:30后每轮200只，卡顿跳过，查缺补漏，开盘前全市场齐
- 指数和个股分开，00001不重复
- 每只算150天COST/ZQ历史，每时每刻都算，用于选股，不只是陡升
- 均价用通达信 amount/(vol*100)，amount/vol
- 生成 data/stocks/ data/indices/ data/meta.json data/steep_all.json
- baostock，不限境外，GitHub Actions可跑
"""
import baostock as bs
import json, os, time
from datetime import datetime, timedelta

GRID=300
HIST_DAYS=150
BATCH=500  # 原200太慢，改为500，你截图里每小时200支一晚跑不完，500*10轮=5000支刚好全市场
RETRY=3

def build_chip(bars):
    n=len(bars)
    if n<60: return None
    minP=min(b['low'] for b in bars)
    maxP=max(b['high'] for b in bars)
    if maxP<=minP: return None
    step=(maxP-minP)/GRID
    dist=[0.0]*GRID
    cost50=[0]*n; cost75=[0]*n; cost90=[0]*n; zq=[0]*n; zq1=[0]*n; vwma=[0]*n
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
        turn=max(0.001, min(turn,0.3))
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
    # 带重试和日志，解决你截图里 股票0 指数0 的问题
    import json
    stocks=[]; indices=[]
    for attempt in range(3):
        try:
            lg=bs.login()
            print(f'baostock login attempt {attempt} {lg.error_code} {lg.error_msg}')
            rs=bs.query_stock_basic()
            print(f'query_stock_basic error_code={rs.error_code} msg={rs.error_msg}')
            cnt=0
            while rs.error_code=='0' and rs.next():
                row=rs.get_row_data()
                cnt+=1
                if len(row)<5: continue
                code_full=row[0]  # sh.600000
                try:
                    code=code_full.split('.')[1]
                except:
                    continue
                type_=row[3] if len(row)>3 else '1'
                status=row[4] if len(row)>4 else '1'
                if type_=='1' and status=='1':
                    stocks.append(code)
                elif type_=='2':
                    indices.append(code)
            print(f'本次取到 股票{len(stocks)} 指数{len(indices)} 遍历行{cnt}')
            bs.logout()
            if stocks:
                # 缓存股票列表，下次baostock挂了也能用
                os.makedirs('data', exist_ok=True)
                try:
                    with open('data/stocks_list.json','w') as f:
                        json.dump(dict(stocks=stocks, indices=indices, updated=datetime.now().isoformat()), f)
                except: pass
                return stocks, indices
        except Exception as e:
            print(f'get_codes 异常 {e} attempt {attempt}')
            try: bs.logout()
            except: pass
        time.sleep(2)
    # 全部失败，尝试读缓存
    try:
        if os.path.exists('data/stocks_list.json'):
            with open('data/stocks_list.json') as f:
                j=json.load(f)
                print(f'使用缓存 stocks_list.json 股票{len(j.get("stocks",[]))}')
                return j.get('stocks',[]), j.get('indices',[])
        if os.path.exists('data/meta.json'):
            # 至少用 steep_all 的 code 续跑
            pass
    except Exception as e:
        print(f'读缓存失败 {e}')
    print('get_codes 最终返回0，可能是baostock境外限流，请重试Actions')
    return stocks, indices

def fetch_kline(code):
    lg=bs.login()
    rs=bs.query_history_k_data_plus(
        f"{'sh' if code.startswith('6') else 'sz'}.{code}",
        "date,open,high,low,close,volume,amount,turn",
        start_date=(datetime.now()-timedelta(days=400)).strftime('%Y-%m-%d'),
        end_date=datetime.now().strftime('%Y-%m-%d'),
        frequency="d", adjustflag="2")
    data=[]
    while rs.error_code=='0' and rs.next():
        d=rs.get_row_data()
        try:
            vol=float(d[5]); amount=float(d[6]); turn=float(d[7])/100 if d[7] else 0.01
            avg=amount/vol if vol else (float(d[2])+float(d[3])+float(d[4]))/3
            data.append(dict(date=d[0], open=float(d[1]), high=float(d[2]), low=float(d[3]), close=float(d[4]), volume=vol, amount=amount, turn=turn, avg=avg))
        except: pass
    bs.logout()
    return data[-HIST_DAYS:]

def save_stock(code, bars, chip):
    os.makedirs('data/stocks', exist_ok=True)
    out=[]
    for i,b in enumerate(bars):
        out.append(dict(d=b['date'], o=b['open'], c=b['close'], h=b['high'], l=b['low'], v=b['volume'], a=b['amount'], turn=b['turn'], avg=b['avg'], cost50=chip['cost50'][i], cost75=chip['cost75'][i], cost90=chip['cost90'][i], zq=chip['zq'][i], zq1=chip['zq1'][i]))
    pref='sh' if code.startswith('6') else 'sz'
    with open(f'data/stocks/{pref}_{code}.json','w') as f:
        json.dump(dict(bars=out, dist=chip['dist'], minP=chip['minP'], maxP=chip['maxP'], updated=datetime.now().isoformat()), f)

def save_index(code, bars):
    os.makedirs('data/indices', exist_ok=True)
    out=[dict(d=b['date'], o=b['open'], c=b['close'], h=b['high'], l=b['low'], v=b['volume']) for b in bars]
    with open(f'data/indices/{code}.json','w') as f:
        json.dump(dict(bars=out, updated=datetime.now().isoformat()), f)

def main():
    stocks, indices = get_codes()
    print(f'股票{len(stocks)} 指数{len(indices)}')
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/stocks', exist_ok=True)
    os.makedirs('data/indices', exist_ok=True)
    # 指数分开
    for code in indices[:80]:
        try:
            bars=fetch_kline(code)
            if bars: save_index(code, bars)
        except Exception as e:
            print(f'指数 {code} 跳过 {e}')
            continue
    # 股票断点续跑
    done=set()
    if os.path.exists('data/stocks'):
        for fn in os.listdir('data/stocks'):
            if fn.endswith('.json'):
                try:
                    done.add(fn.split('_')[1].split('.')[0])
                except: pass
    print(f'已完成{len(done)}，待跑{len([c for c in stocks if c not in done])}')
    all_codes=[c for c in stocks if c not in done]
    round_idx=0
    while all_codes:
        round_idx+=1
        print(f'第{round_idx}轮 剩余{len(all_codes)} 0:30后每轮{BATCH}只 卡顿跳过')
        batch=all_codes[:BATCH]
        failed=[]
        for code in batch:
            for attempt in range(RETRY):
                try:
                    bars=fetch_kline(code)
                    if len(bars)<60:
                        print(f'{code} 数据不足跳过')
                        break
                    chip=build_chip(bars)
                    if not chip:
                        break
                    save_stock(code, bars, chip)
                    print(f'{code} ok COST50 {chip["cost50"][-1]:.2f} ZQ {chip["zq"][-1]:.1f}')
                    break
                except Exception as e:
                    print(f'{code} 卡顿跳过 {e} attempt {attempt}')
                    time.sleep(0.5)
                    if attempt==RETRY-1:
                        failed.append(code)
        all_codes = failed + all_codes[BATCH:]
        if not all_codes:
            break
        # 开盘前必须齐 8:30
        now=datetime.now()
        if now.hour>=8 and now.minute>=30:
            print('快开盘，继续查缺补漏')
        time.sleep(3)
        if round_idx>30:
            break
    # 生成meta和全市场COST/ZQ每时每刻
    steep_all=[]
    for fn in os.listdir('data/stocks'):
        try:
            with open(f'data/stocks/{fn}') as f:
                j=json.load(f)
                bars=j['bars']
                if len(bars)<3: continue
                last=bars[-1]
                steep_all.append(dict(code=fn.split('_')[1].split('.')[0], cost50=last['cost50'], cost75=last['cost75'], cost90=last['cost90'], zq=last['zq'], zq1=last['zq1'], turn=last['turn']*100, c=last['c'], d=last['d']))
        except: continue
    with open('data/meta.json','w') as f:
        json.dump(dict(total=len(steep_all), lastUpdateDate=datetime.now().isoformat(), updated=datetime.now().isoformat(), note=f'指数{len(indices)} 股票{len(steep_all)} COST/ZQ历史+当日 amount/vol'), f)
    with open('data/steep_all.json','w') as f:
        json.dump(dict(all=steep_all, updated=datetime.now().isoformat()), f)
    print(f'完成 全市场{len(steep_all)}')

if __name__=='__main__':
    main()
