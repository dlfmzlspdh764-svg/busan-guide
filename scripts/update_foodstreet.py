#!/usr/bin/env python3
"""부산 음식테마거리 OPEN API(redtable) → foodstreet.json. 키: env BUSAN_FOOD_API_KEY"""
import json, os, sys, time, urllib.request, datetime
from concurrent.futures import ThreadPoolExecutor
B = "https://busan-food.openapi.redtable.global/api/menu/korean"
K = os.environ["BUSAN_FOOD_API_KEY"]
def get(pg, tries=4):
    for t in range(tries):
        try:
            u = f"{B}?serviceKey={K}&pageNo={pg}&numOfRows=1000"
            with urllib.request.urlopen(u, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            err = type(e).__name__
            time.sleep(2 + t * 3)
    print("page fail", pg, err); return None
first = get(1)
if not first or first.get("header", {}).get("resultCode") != "00":
    print("API error", (first or {}).get("header")); sys.exit(1)
total = first["header"]["totalCount"]; pages = (total + 999) // 1000
rows = list(first["body"])
with ThreadPoolExecutor(8) as ex:
    for d in ex.map(get, range(2, pages + 1)):
        if d and d.get("body"): rows += d["body"]
print("rows", len(rows), "/", total)
seen = set(); R = {}
for x in rows:
    if x["MENU_ID"] in seen: continue
    seen.add(x["MENU_ID"])
    rid = x["RSTR_ID"]
    r = R.setdefault(rid, {"id": rid, "n": (x["RSTR_NM"] or "").strip(), "gu": (x["AREA_NM"] or "").replace("부산광역시", "").strip(), "m": []})
    nm = (x["MENU_NM"] or "").strip()
    if nm and all(nm != a[0] for a in r["m"]):
        r["m"].append([nm, x["MENU_PRICE"] or 0, 1 if x.get("SPCLT_MENU_YN") == "Y" else 0])
G = {}
for r in R.values():
    if not r["n"] or not r["m"]: continue
    r["m"].sort(key=lambda a: (-a[2], a[1] or 9e9)); r["m"] = r["m"][:15]
    G.setdefault(r["gu"] or "기타", []).append(r)
streets = [{"name": g, "places": sorted(v, key=lambda r: r["n"])} for g, v in sorted(G.items(), key=lambda kv: -len(kv[1]))]
out = {"updated": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
       "source": "부산 음식테마거리 OPEN API (레드테이블)", "total_menus": len(seen), "streets": streets}
json.dump(out, open("foodstreet.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("groups", len(streets), "places", sum(len(s["places"]) for s in streets), "menus", len(seen))
