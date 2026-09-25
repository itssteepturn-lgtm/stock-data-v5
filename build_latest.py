import baostock as bs
import json, os, time, subprocess, pathlib
from datetime import datetime, timedelta

HIST_DIR="data/history"
os.makedirs(HIST_DIR, exist_ok=True)
INDEX_CODES=['000001','399001','399006','000688','899050','000300','000905']

def login():
    lg=bs.login()
    if lg.error_code!='0':
        time.sleep(3)
        return login()
    print("baostock login ok")
    return True

def fetch_kline(code, is_idx=False, days=400):
    if is_idx:
        if code=='000001': bs_code='sh.000001'
        elif code=='000688': bs_code='sh.000688'
        elif code=='000300': bs_code='sh.000300'
        elif code=='000905': bs_code='sh.000905'
        elif code.startswith('399'): bs_code=f'sz.{code}'
        else: bs_code=f'sh.{code}' if code.startswith('6') else f'sz.{code}'
        adjust="3"
        fname=f"idx_sh_{code}.json" if code in ['000001','000688'] else f"idx_{code}.json"
    else:
        pref='sh' if code.startswith('6') or code.startswith('68') else 'sz'
        bs_code=f"{pref}.{code}"
        adjust="2"
        fname=f"{pref}_{code}.json"

    end=datetime.now().strftime("%Y-%m-%d")
    start=(datetime.now()-timedelta(days=days*2)).strftime("%Y-%m-%d")
    try:
        # 尝试取turn换手率，baostock支持turn
        rs=bs.query_history_k_data_plus(bs_code,
            "date,open,high,low,close,volume,amount,turn",
            start_date=start, end_date=end, frequency="d", adjustflag=adjust)
        if rs.error_code!='0':
            rs=bs.query_history_k_data_plus(bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start, end_date=end, frequency="d", adjustflag=adjust)
        bars=[]
        while rs.error_code=='0' and rs.next():
            r=rs.get_row_data()
            try:
                o=float(r[1]); h=float(r[2]); l=float(r[3]); c=float(r[4]); v=float(r[5]); a=float(r[6])
                turn=float(r[7]) if len(r)>7 and r[7]!='' else 0
                # turn可能是%，如0.68表示0.68%，转小数
                if turn>1: turn=turn/100
                bars.append({"d":r[0],"o":o,"h":h,"l":l,"c":c,"v":v,"a":a,"turn":turn})
            except: continue
        if len(bars)<20:
            return None, None
        return bars[-400:], fname
    except Exception as e:
        print(f"{code} err {e}")
        return None, None

def main():
    login()
    p=pathlib.Path("data/codes.json")
    if p.exists():
        codes=json.loads(p.read_text())
    else:
        rs=bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
        codes=[]
        while rs.error_code=='0' and rs.next():
            row=rs.get_row_data()
            code=row[0]
            if code.startswith("sh.") or code.startswith("sz."):
                c=code.split(".")[1]
                codes.append(c)
        pathlib.Path("data/codes.json").write_text(json.dumps(codes),encoding='utf-8')
    print(f"codes {len(codes)}")

    for idx in INDEX_CODES:
        bars, fname=fetch_kline(idx, is_idx=True, days=400)
        if bars:
            (pathlib.Path(HIST_DIR)/fname).write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
            print(f"指数 {idx} -> {fname} {bars[-1]['c']} turn={bars[-1].get('turn')}")

    shard=int(os.getenv('SHARD','0'))
    total_shards=int(os.getenv('TOTAL_SHARDS','1'))
    chunk=(len(codes)+total_shards-1)//total_shards
    s=shard*chunk
    e=min(s+chunk, len(codes))
    target=codes[s:e]
    print(f"SHARD {shard}/{total_shards} {s}-{e} {len(target)}")

    ok=0
    for i, code in enumerate(target):
        if code in INDEX_CODES:
            continue
        bars, fname=fetch_kline(code, is_idx=False, days=400)
        if bars:
            (pathlib.Path(HIST_DIR)/fname).write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
            if code=='000001':
                (pathlib.Path(HIST_DIR)/f"{code}.json").write_text(json.dumps(bars,ensure_ascii=False),encoding='utf-8')
            ok+=1
        if i%100==0:
            print(f"[{i}/{len(target)}] ok={ok}")

    all_files=list(pathlib.Path(HIST_DIR).glob("*.json"))
    meta={"updated":datetime.now().isoformat(),"saved_total":len(all_files),"v":"V7 筹码分布+turn实时"}
    pathlib.Path("data/meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)
    bs.logout()

if __name__=="__main__":
    main()
