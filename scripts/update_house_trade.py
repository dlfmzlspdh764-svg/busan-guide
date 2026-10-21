#!/usr/bin/env python3
"""부산광역시 주택 매매 실거래 (6260000/HouseTradePriceService/getHouseTradePrice) -> realestate_trade.json"""
import os, json, time, urllib.request, urllib.parse, collections
from datetime import datetime, timedelta, timezone
KEY=(os.environ.get("BUSAN_HOUSE_KEY") or os.environ.get("DATA_GO_KR_KEY") or "").strip()
URL="https://apis.data.go.kr/6260000/HouseTradePriceService/getHouseTradePrice"
KST=timezone(timedelta(hours=9))
def get(p):
    q=f"serviceKey={urllib.parse.quote(KEY,safe='')}&pageNo={p}&numOfRows=1000&resultType=json"
    for i in range(4):
        try:
            with urllib.request.urlopen(URL+"?"+q,timeout=60) as r: d=json.loads(r.read().decode("utf-8","replace"))
            h=d["response"]["header"]
            if h.get("resultCode") not in ("00","0"): raise SystemExit(f"API 오류 code={h.get('resultCode')} msg={h.get('resultMsg')}")
            return d["response"]["body"]
        except SystemExit: raise
        except Exception as e: err=e; time.sleep(5)
    raise err
def f(x):
    try: return float(x)
    except: return 0.0
def main():
    if not KEY: raise SystemExit("키 없음")
    b=get(1); tot=int(b["totalCount"]); raw=[]
    p=1
    while True:
        it=(b.get("items") or {}).get("item") or []
        if isinstance(it,dict): it=[it]
        raw+=it
        if p*1000>=tot or not it: break
        p+=1; b=get(p)
    print("fetched",len(raw),"of",tot,flush=True)
    yms=sorted({r.get("ctrtYm") for r in raw if r.get("ctrtYm")},reverse=True)
    keep=set(yms[:3])
    g=collections.defaultdict(list); types=collections.Counter()
    for r in raw:
        types[r.get("hsTypeNm") or "-"]+=1
        if r.get("ctrtYm") not in keep: continue
        parts=(r.get("sggNm") or "").split()
        gu=parts[1] if len(parts)>1 else "기타"; dong=" ".join(parts[2:])
        ym=r["ctrtYm"]
        g[gu].append({"t":r.get("hsTypeNm") or "","nm":r.get("bldgNm") or "","dong":dong,"road":r.get("roadNm") or "",
            "amt":int(f(r.get("dlngAmt"))),"ar":f(r.get("tflar")),"land":f(r.get("siar")),"fl":r.get("flr") or "",
            "by":r.get("archYr") or "","d":f"{ym[:4]}-{ym[4:]}-{int(f(r.get('ctrtDay'))):02d}","se":r.get("dlngSeNm") or ""})
    gus=[];summ={}
    for gu in sorted(g):
        rows=sorted(g[gu],key=lambda x:x["d"],reverse=True)
        a=[x["amt"] for x in rows if x["amt"]]
        summ[gu]={"n":len(rows),"avg":round(sum(a)/len(a)) if a else 0}
        gus.append({"gu":gu,"rows":rows})
    json.dump({"upd":datetime.now(KST).strftime("%Y-%m-%d %H:%M"),"months":sorted(keep),"total_api":tot,"types_all":dict(types),
        "summary":summ,"gus":gus,"src":"부산광역시 주택 매매 실거래가 (공공데이터포털)"},open("realestate_trade.json","w"),ensure_ascii=False,separators=(",",":"))
    print("months",sorted(keep),"types",dict(types),"kept",sum(s["n"] for s in summ.values()))
main()
