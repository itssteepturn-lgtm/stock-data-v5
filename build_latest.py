"""
V5全功能版 - build_latest.py 测试版
- 只抓 7 只测试股，150天，前复权
- 均价 avg = amount / volume (baostock 股数)
- 换手 turn = baostock turn(%) /100，限幅 0.1%-30%
- 筹码：GRID=300，三角分布峰值在avg，dist*= (1-turn) 衰减
- 对标通达信，存 data/stocks/sh_xxx.json + meta.json + steep_all.json
- iPhone专用：可在 Actions 直接 python build_latest.py 跑
"""
import os
import json
import time
import traceback
from datetime import datetime, timedelta

import baostock as bs

GRID = 300
HIST_DAYS = 150
RETRY = 2
BATCH_SLEEP = 0.5

# 测试7只
TEST_STOCKS = ["300313", "600519", "600127", "003006", "002909", "920706", "688137"]

def to_sh_sz(code):
    code = str(code).zfill(6)
    if code.startswith('6'):
        return f"sh.{code}", f"sh_{code}.json", f"1.{code}"
    else:
        return f"sz.{code}", f"sz_{code}.json", f"0.{code}"

def build_chip(bars):
    n = len(bars)
    if n == 0:
        return None
    minP = min(b['low'] for b in bars)
    maxP = max(b['high'] for b in bars)
    if maxP <= minP:
        maxP = minP * 1.1
    step = (maxP - minP) / GRID
    if step <= 0:
        step = maxP * 0.001 or 0.01

    dist = [0.0] * GRID
    cost50 = [0]*n
    cost75 = [0]*n
    cost90 = [0]*n
    zq = [0]*n
    zq1 = [0]*n
    vwma = [0]*n

    for i in range(n):
        sCV = 0.0
        sV = 0.0
        for k in range(max(0, i-9), i+1):
            sCV += bars[k]['close'] * bars[k]['volume']
            sV += bars[k]['volume']
        vwma[i] = sCV / sV if sV else bars[i]['close']

    for i in range(n):
        b = bars[i]
        turn = b.get('turn', 0.01)
        turn = max(0.001, min(turn, 0.3))

        for g in range(GRID):
            dist[g] *= (1.0 - turn)

        low = b['low']
        high = b['high']
        avg = b.get('avg', b['close'])

        def price_to_idx(p):
            idx = int((p - minP) / step)
            return max(0, min(GRID-1, idx))

        lowIdx = price_to_idx(low)
        highIdx = price_to_idx(high)
        avgIdx = price_to_idx(avg)
        if lowIdx > highIdx:
            lowIdx, highIdx = highIdx, lowIdx
        avgIdx = max(lowIdx, min(highIdx, avgIdx))

        weights = []
        idxs = []
        for g in range(lowIdx, highIdx+1):
            idxs.append(g)
            w = 1.0
            if highIdx != lowIdx:
                if g <= avgIdx:
                    denom = (avgIdx - lowIdx) or 1
                    w = (g - lowIdx) / denom
                else:
                    denom = (highIdx - avgIdx) or 1
                    w = (highIdx - g) / denom
                if w < 0.05 and (g == lowIdx or g == highIdx):
                    w = 0.05
            weights.append(max(0.0, w))

        sumW = sum(weights) or 1.0
        for j, g in enumerate(idxs):
            dist[g] += weights[j] / sumW * turn

        total = sum(dist) or 1.0
        cum = 0.0
        c50 = c75 = c90 = 0.0
        for g in range(GRID):
            cum += dist[g]
            ratio = cum / total
            price = minP + g * step
            if not c50 and ratio >= 0.5:
                c50 = price
            if not c75 and ratio >= 0.75:
                c75 = price
            if not c90 and ratio >= 0.9:
                c90 = price

        cost50[i] = c50 or b['close']
        cost75[i] = c75 or b['close']
        cost90[i] = c90 or b['close']

        def winner(price):
            win = 0.0
            for g in range(GRID):
                if minP + g * step <= price:
                    win += dist[g]
            return win / total * 100.0

        zq[i] = winner(b.get('avg', b['close']))
        zq1[i] = winner(vwma[i])

    return dict(cost50=cost50, cost75=cost75, cost90=cost90, zq=zq, zq1=zq1, vwma=vwma, minP=minP, maxP=maxP, dist=dist)

def fetch_baostock(code_full):
    bs.login()
    try:
        start_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            code_full,
            "date,open,high,low,close,volume,amount,turn",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"
        )
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            print(f"  [warn] {code_full} 无数据")
            return []

        bars = []
        for row in data_list:
            try:
                d, o, h, l, c, v, a, t = row
                o = float(o); h = float(h); l = float(l); c = float(c)
                v = float(v)
                a = float(a)
                t = float(t) if t not in ('', None) else 0.0
                avg = a / v if v else (o+h+l+c)/4.0
                turn = t / 100.0 if t > 1 else t
                if turn == 0:
                    turn = 0.01
                bars.append(dict(
                    date=d,
                    open=o, high=h, low=l, close=c,
                    volume=v, amount=a, turn=turn, avg=avg
                ))
            except Exception as e:
                print(f"  parse error {row} {e}")
                continue

        bars = bars[-HIST_DAYS:]
        return bars
    finally:
        bs.logout()

def save_stock(code, bars, chip):
    pref, fname, secid = to_sh_sz(code)
    os.makedirs("data/stocks", exist_ok=True)

    out_bars = []
    for i, b in enumerate(bars):
        out_bars.append(dict(
            d=b['date'],
            o=round(b['open'], 3),
            h=round(b['high'], 3),
            l=round(b['low'], 3),
            c=round(b['close'], 3),
            v=b['volume'],
            a=b['amount'],
            turn=round(b['turn'], 6),
            avg=round(b['avg'], 3),
            cost50=round(chip['cost50'][i], 3),
            cost75=round(chip['cost75'][i], 3),
            cost90=round(chip['cost90'][i], 3),
            zq=round(chip['zq'][i], 2),
            zq1=round(chip['zq1'][i], 2),
            vwma=round(chip['vwma'][i], 3),
        ))

    out = dict(
        code=code,
        secid=secid,
        minP=chip['minP'],
        maxP=chip['maxP'],
        dist=chip['dist'],
        bars=out_bars,
        updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        count=len(out_bars)
    )
    path = f"data/stocks/{fname}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"  saved {path} last COST {out_bars[-1]['cost50']}/{out_bars[-1]['cost75']}/{out_bars[-1]['cost90']} ZQ {out_bars[-1]['zq']}")
    return out

def main():
    codes = TEST_STOCKS
    env_codes = os.getenv("STOCK_CODES")
    if env_codes:
        codes = [c.strip() for c in env_codes.split(",") if c.strip()]

    clean = os.getenv("CLEAN", "false").lower() == "true"
    if clean:
        import shutil
        if os.path.exists("data/stocks"):
            shutil.rmtree("data/stocks")

    os.makedirs("data/stocks", exist_ok=True)
    os.makedirs("data/indices", exist_ok=True)

    all_ok = []
    failed = []

    for code in codes:
        print(f"\n== {code} ==")
        for attempt in range(RETRY+1):
            try:
                bars = fetch_baostock(to_sh_sz(code)[0])
                if not bars or len(bars) < 30:
                    raise ValueError(f"bars too few {len(bars)}")
                chip = build_chip(bars)
                if not chip:
                    raise ValueError("chip None")
                saved = save_stock(code, bars, chip)
                all_ok.append(dict(code=code, last=saved['bars'][-1]))
                break
            except Exception as e:
                print(f"  attempt {attempt} fail {e}")
                traceback.print_exc()
                if attempt < RETRY:
                    time.sleep(BATCH_SLEEP)
                else:
                    failed.append(code)
        time.sleep(BATCH_SLEEP)

    meta = dict(
        total=len(all_ok),
        failed=failed,
        updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        grid=GRID,
        hist_days=HIST_DAYS,
        method="baostock amount/volume + turn% + triangle + decay + 300grid",
        stocks=[a['code'] for a in all_ok]
    )
    os.makedirs("data", exist_ok=True)
    with open("data/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    steep = []
    for a in all_ok:
        last = a['last']
        steep.append(dict(
            code=a['code'],
            c=last['c'],
            cost50=last['cost50'],
            cost75=last['cost75'],
            cost90=last['cost90'],
            zq=last['zq'],
            zq1=last['zq1'],
            turn=last['turn']
        ))
    with open("data/steep_all.json", "w", encoding="utf-8") as f:
        json.dump(dict(updated=meta['updated'], data=steep), f, ensure_ascii=False, indent=2)

    print(f"\nDone ok={len(all_ok)} failed={failed}")

if __name__ == "__main__":
    main()
