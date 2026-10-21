#!/usr/bin/env python3
"""부산 아파트 전월세 실거래가 (국토교통부, data.go.kr) -> realestate.json"""
import os, json, sys, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
GU = {"26110":"중구","26140":"서구","26170":"동구","26200":"영도구","26230":"부산진구","26260":"동래구","26290":"남구","26320":"북구","26350":"해운대구","26380":"사하구","26410":"금정구","26440":"강서구","26470":"연제구","26500":"수영구","26530":"사상구","26710":"기장군"}
KST = timezone(timedelta(hours=9))
def months(n=3):
    d = datetime.now(KST).replace(day=1); out = []
    for _ in range(n):
        out.append(d.strftime("%Y%m")); d = (d - timedelta(days=1)).replace(day=1)
    return out
def num(s):
    try: return int(str(s).replace(",", "").strip())
    except: return 0
def fetch(lawd, ym, page, enc):
    k = urllib.parse.quote(KEY, safe="") if enc else KEY
    q = f"serviceKey={k}&LAWD_CD={lawd}&DEAL_YMD={ym}&pageNo={page}&numOfRows=1000"
    for i in range(3):
        try:
            with urllib.request.urlopen(URL + "?" + q, timeout=40) as r: return r.read().decode("utf-8", "replace")
        except Exception as e:
            err = e; time.sleep(3)
    raise err
ENC = False
def get(lawd, ym, page):
    global ENC
    x = fetch(lawd, ym, page, ENC)
    if "<items" not in x and not ENC and "SERVICE_KEY" in x.upper():
        ENC = True; x = fetch(lawd, ym, page, ENC)
    try: root = ET.fromstring(x)
    except Exception: raise SystemExit("API 응답 오류: " + x[:300])
    code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
    if code not in ("00", "000"):
        raise SystemExit(f"API 오류 code={code} msg={(root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg') or '').strip()}")
    return root
def main():
    if not KEY: raise SystemExit("DATA_GO_KR_KEY 없음")
    yms = months(3); out = []; summ = {}
    for lawd, gu in GU.items():
        rows = []
        for ym in yms:
            page = 1
            while True:
                root = get(lawd, ym, page)
                items = root.findall(".//item")
                for it in items:
                    g = lambda t: (it.findtext(t) or "").strip()
                    ar = float(g("excluUseAr") or 0)
                    rows.append({"apt": g("aptNm"), "dong": g("umdNm"), "ar": round(ar, 2), "py": round(ar / 3.3058, 1),
                        "fl": g("floor"), "dep": num(g("deposit")), "mon": num(g("monthlyRent")),
                        "d": f"{g('dealYear')}-{num(g('dealMonth')):02d}-{num(g('dealDay')):02d}",
                        "ct": g("contractType"), "pdep": num(g("preDeposit")), "pmon": num(g("preMonthlyRent")),
                        "by": g("buildYear"), "term": g("contractTerm")})
                tot = num(root.findtext(".//totalCount"))
                if page * 1000 >= tot or not items: break
                page += 1
        rows.sort(key=lambda r: r["d"], reverse=True)
        js = [r["dep"] for r in rows if r["mon"] == 0]
        summ[gu] = {"n": len(rows), "jn": len(js), "wn": len(rows) - len(js), "javg": round(sum(js) / len(js)) if js else 0}
        out.append({"gu": gu, "code": lawd, "rows": rows})
        print(gu, summ[gu], flush=True)
    json.dump({"upd": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "months": yms, "summary": summ, "gus": out,
               "src": "국토교통부 아파트 전월세 실거래가 (공공데이터포털)"}, open("realestate.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("total", sum(s["n"] for s in summ.values()))
main()
