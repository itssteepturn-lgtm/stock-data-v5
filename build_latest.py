import baostock as bs
import json, os, sys, time, subprocess, glob, pathlib
from datetime import datetime, timedelta
import pandas as pd

# V5.11 回归V3最稳 - baostock版，永不再Connection aborted
# V3为什么稳？就是因为用的baostock，不是东财push2his，东财现在限GitHub IP，baostock不限
DATA_DIR="data"
HIST_DIR="data/history"
STOCKS_DIR="data/stocks"
META_FILE="data/meta.json"
os.makedirs(HIST_DIR, exist_ok=True)
os.makedirs(STOCKS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

MAX_DAYS_KEPT=350
TIME_BUDGET_SECONDS=50*60  # 50分钟，GitHub 1小时超时，留10分
CHECKPOINT_EVERY=100

def git_checkpoint(tag):
    try:
        subprocess.run(['git','add','data/'],check=True)
        diff=subprocess.run(['git','diff','--staged','--quiet'])
        if diff.returncode==0: return
        subprocess.run(['git','commit','-m',f'data checkpoint {tag}'],check=True)
        subprocess.run(['git','push'],check=True)
        print(f"已提交 {tag}")
    except Exception as e:
        print(f"checkpoint fail {e}")

def login():
    lg=bs.login()
    if lg.error_code!='0':
        print(f"baostock login fail {lg.error_msg}")
        time.sleep(3)
        return login()
    print("baostock login ok")
    return True

def logout():
    try: bs.logout()
    except: pass

def fetch_all_codes():
    # 优先用本地codes.json，如果没有，用baostock全A股
    p=pathlib.Path("data/codes.json")
    if p.exists():
        try:
            codes=json.loads(p.read_text())
            if len(codes)>3000:
                print(f"用本地codes.json {len(codes)}")
                return codes
        except: pass
    # baostock全A股
    print("用baostock拉全A股列表")
    rs=bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
    codes=[]
    while rs.error_code=='0' and rs.next():
        row=rs.get_row_data()
        code=row[0]  # sh.600000
        if code.startswith("sh.") or code.startswith("sz."):
            c=code.split(".")[1]
            codes.append(c)
    print(f"baostock codes {len(codes)}")
    if len(codes)<1000:
        # 兜底
        return ["600000","000001","300750","600519","000858"]
    pathlib.Path("data/codes.json").write_text(json.dumps(codes,ensure_ascii=False),encoding='utf-8')
    return codes

def fetch_kline_baostock(code, days=350):
    # baostock: sh.600000, d, date=xxx
    prefix='sh' if code.startswith('6') else 'sz'
    bs_code=f"{prefix}.{code}"
    end=datetime.now().strftime("%Y-%m-%d")
    start=(datetime.now()-timedelta(days=days*1.5)).strftime("%Y-%m-%d")
    try:
        rs=bs.query_history_k_data_plus(bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start, end_date=end, frequency="d", adjustflag="2") # 前复权，算cost必须前复权
        if rs.error_code!='0':
            return None
        bars=[]
        while rs.error_code=='0' and rs.next():
            r=rs.get_row_data()
            try:
                bars.append({
                    "d":r[0],
                    "o":float(r[1]),
                    "h":float(r[2]),
                    "l":float(r[3]),
                    "c":float(r[4]),
                    "v":float(r[5]),
                    "a":float(r[6])
                })
            except: continue
        if len(bars)<60:
            return None
        # 只留最后350根
        return bars[-MAX_DAYS_KEPT:]
    except Exception as e:
        print(f"{code} err {e}")
        return None

def build_aggregated_with_cost():
    # 生成 latest.json 带 cost，手机秒级过滤
    all_latest=[]
    for fp in glob.glob(os.path.join(HIST_DIR,"*.json")):
        try:
            with open(fp) as f:
                bars=json.load(f)
            if len(bars)<60: continue
            last=bars[-1]
            prev=bars[-2] if len(bars)>1 else last
            # cost计算 - 按成交量排序，V3同款
            slice_bars=bars[-200:]
            total_vol=sum(b["v"] for b in slice_bars) or 1
            sorted_bars=sorted(slice_bars, key=lambda x: x["c"])
            def cost_pct(pct):
                cum=0
                for b in sorted_bars:
                    cum+=b["v"]
                    if cum/total_vol*100>=pct:
                        return b["c"]
                return sorted_bars[-1]["c"]
            code=os.path.basename(fp).replace('.json','')
            all_latest.append({
                "c":code,
                "p":last["c"],
                "d":last["d"],
                "chg": round((last["c"]-prev["c"])/prev["c"]*100,2) if prev["c"] else 0,
                "cost50": round(cost_pct(50),2),
                "cost75": round(cost_pct(75),2),
                "cost90": round(cost_pct(90),2),
                "vol": last["v"]
            })
        except Exception as e:
            # print(f"agg {fp} {e}")
            pass
    # 排序按cost陡升潜力？先按代码
    all_latest.sort(key=lambda x: x["c"])
    os.makedirs("data",exist_ok=True)
    with open("data/latest.json","w",encoding='utf-8') as f:
        json.dump(all_latest,f,ensure_ascii=False,separators=(',',':'))
    print(f"聚合 latest.json {len(all_latest)}只，已含cost50/75/90")
    return all_latest

def main():
    start_time=time.time()
    login()
    codes=fetch_all_codes()
    # 分片
    shard=int(os.getenv('SHARD','0'))
    total_shards=int(os.getenv('TOTAL_SHARDS','2'))
    chunk=(len(codes)+total_shards-1)//total_shards
    s=shard*chunk
    e=min(s+chunk, len(codes))
    target=codes[s:e]
    print(f"SHARD {shard}/{total_shards} {s}-{e} total {len(codes)} target {len(target)}")

    ok=0; fail=0; cleaned=0
    # 清理假数据
    for f in pathlib.Path(HIST_DIR).glob("*.json"):
        try:
            arr=json.loads(f.read_text())
            if not arr: continue
            fake=0
            for b in arr[:5]:
                if isinstance(b,dict):
                    c=b.get('c',0); v=b.get('v',0)
                    if 9.5<c<11.5 and abs(v-1000)<1:
                        fake+=1
            if fake>=3:
                f.unlink(); cleaned+=1
        except: pass
    print(f"cleaned fake {cleaned}")

    for i, code in enumerate(target):
        # 超时保护
        if time.time()-start_time > TIME_BUDGET_SECONDS:
            print(f"时间到 {TIME_BUDGET_SECONDS}s，提前checkpoint")
            git_checkpoint(f"shard{shard} mid {i}")
            break

        existing=pathlib.Path(HIST_DIR)/f"{code}.json"
        if existing.exists():
            try:
                bars=json.loads(existing.read_text())
                if bars and len(bars)>=60:
                    last_d=bars[-1].get('d','')
                    if last_d>=datetime.now().strftime("%Y-%m-%d"):
                        ok+=1
                        continue
                    # 如果是昨天的，跳过，今天才补
                    if last_d>=(datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d"):
                        ok+=1
                        continue
            except: pass

        bars=fetch_kline_baostock(code, days=MAX_DAYS_KEPT)
        if bars is None:
            fail+=1
            if i%50==0:
                print(f"[{i}/{len(target)}] {code} FAIL ok={ok} fail={fail}")
        else:
            try:
                existing.write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
                ok+=1
                if i%50==0:
                    print(f"[{i}/{len(target)}] {code} OK {bars[-1]['c']} ok={ok} fail={fail}")
            except:
                fail+=1

        if i>0 and i%CHECKPOINT_EVERY==0:
            git_checkpoint(f"shard{shard} {i}/{len(target)}")

        time.sleep(0.3)  # baostock不需要慢，0.3秒就行，不会被踢

    # 最后聚合
    build_aggregated_with_cost()

    meta={
        "updated":datetime.now().isoformat(),
        "count":len(codes),
        "shard":f"{shard}/{total_shards}",
        "range":f"{s}-{e}",
        "ok":ok,"fail":fail,
        "cleaned_fake":cleaned,
        "saved_total":len(list(pathlib.Path(HIST_DIR).glob("*.json"))),
        "v":"V5.11 baostock回归版-永不aborted",
        "note":"baostock主源，V3同款所以稳，不再Connection aborted；前复权350天；COST/ZQ/ZQ1全部参与今日，断档前端补"
    }
    pathlib.Path(META_FILE).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)
    git_checkpoint(f"shard{shard} final")
    logout()

if __name__=="__main__":
    main()
