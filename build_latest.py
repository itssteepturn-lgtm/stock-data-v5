import json, os, time, datetime, pathlib, requests, random

DATA_DIR = pathlib.Path("data")
HIST_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

# 简化版：拉取A股列表和K线，写入自家data，手机读自己仓库
# 实际你原来的build_latest.py逻辑放这里，核心是产出 codes.json meta.json history/*.json

def fetch_codes():
    # 示例：用东财接口拉全A股，真实版用你原来的逻辑
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fidf=1&fid0=mkt&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    try:
        r = requests.get(url, timeout=15).json()
        codes = [i['f12'] for i in r['data']['diff'][:4500]]
        return codes
    except:
        return ["000001","600519","000858","300750"]

def fetch_kline(code):
    # 示例占位：真实用 eastmoney kline
    return [{"c":10+random.random(),"v":1000} for _ in range(90)]

def main():
    codes = fetch_codes()
    (DATA_DIR/"codes.json").write_text(json.dumps(codes,ensure_ascii=False),encoding='utf-8')
    for c in codes[:2000]: # Actions里分批，首次2000，下次全量，避免超时
        try:
            k = fetch_kline(c)
            (HIST_DIR/f"{c}.json").write_text(json.dumps(k),encoding='utf-8')
            time.sleep(0.02)
        except: pass
    meta={"updated":datetime.datetime.now().isoformat(),"count":len(codes),"v":"V5自养版"}
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
    print(f"done {len(codes)}")

if __name__=="__main__":
    main()
