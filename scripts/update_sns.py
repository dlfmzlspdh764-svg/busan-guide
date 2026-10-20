#!/usr/bin/env python3
"""SNS 화제 맛집 TOP 20: 2026.1~9 유튜브·블로그·뉴스·맛집사이트 언급, 기존 랭킹 제외, 카카오 검증."""
import json, os, re, sys, time, datetime, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_hot as H

ROOT = H.ROOT
OUT = os.path.join(ROOT, "sns.json")
FOODCATE = re.compile(r"음식점|한식|중식|일식|양식|아시아|분식|치킨|피자|뷔페|횟집|해물|육류|고기|국밥|밀면|냉면|국수|술집|카페|디저트|베이커리|빵")
Q = ["부산 맛집", "부산 현지인 맛집", "부산 노포", "서면 맛집", "해운대 맛집", "광안리 맛집", "남포동 맛집",
     "전포 맛집", "부산 국밥 맛집", "부산 밀면 맛집", "기장 맛집", "영도 맛집", "부산 줄서는 맛집", "동래 맛집"]
GENERIC = re.compile(r"^(근처|숨은|청년|또간집|생선구이|큰집|미식|아침점심|감성|맛집|노포|현지인|부산|횟집|국밥|밀면|돼지|한식|백반|식당|찐|전국|동네)")
NSO = "so%3Ar%2Cp%3Afrom20260101to20260930"

def blog(q):
    url = "https://search.naver.com/search.naver?where=blog&query=%s&nso=%s" % (urllib.parse.quote(q), NSO)
    try: raw = H.fetch(url, headers={"Referer": "https://search.naver.com/"}).decode("utf-8", "ignore")
    except Exception as e: H.log("blog", e); return []
    out, seen = [], set()
    for m in re.finditer(r'href="https://(?:blog|cafe)\.naver\.com/[^"]+"[^>]*>(.*?)</a>', raw, re.S):
        t = H.strip_html(m.group(1))
        if len(t) >= 8 and t not in seen: seen.add(t); out.append({"title": t, "src": "blog"})
    return out[:40]

def gnews(q, site=None):
    qq = q + (" site:" + site if site else "") + " after:2026-01-01 before:2026-10-01"
    try: items = H.parse_gnews(qq)
    except Exception as e: H.log("gn", e); return []
    s = "youtube" if site == "youtube.com" else "site" if site else "news"
    for it in items: it["src"] = s
    return items

def youtube(q):
    out = []
    for it in H.parse_youtube(q + " 2026"):
        out.append(it)
    return out

def diningcode(q):
    url = "https://www.diningcode.com/list.dc?query=" + urllib.parse.quote(q)
    try: raw = H.fetch(url).decode("utf-8", "ignore")
    except Exception as e: H.log("dc", e); return []
    names = set(re.findall(r'"nm"\s*:\s*"([^"]{2,30})"', raw)) | set(re.findall(r'class="InfoHeader"[^>]*>\s*<h2>\s*\d*\.?\s*([^<]{2,30})<', raw))
    return [{"title": "'" + n.strip() + "'", "src": "site"} for n in names]

def main():
    db = json.load(open(H.FOOD, encoding="utf-8"))
    excl_id, excl_nm = set(), set()
    for k in ("food", "sushi", "chinese", "family"):
        for p in db.get(k) or []:
            excl_id.add(str(p.get("id"))); excl_nm.add(re.sub(r"\s+", "", p.get("n", "")))
    try:
        for p in json.load(open(os.path.join(ROOT, "hot.json"))).get("places") or []:
            excl_id.add(str(p.get("id"))); excl_nm.add(re.sub(r"\s+", "", p.get("n", "")))
    except Exception: pass
    cands, ok = {}, {}
    def add(items):
        for it in items:
            ok[it["src"]] = ok.get(it["src"], 0) + 1
            for n in H.extract_candidates(it["title"]):
                m = cands.setdefault(n, {"news": 0, "blog": 0, "youtube": 0, "site": 0, "t": []})
                m[it["src"]] += 1
                if len(m["t"]) < 2: m["t"].append(it["title"][:90])
    for q in Q:
        add(gnews(q)); add(gnews(q, "youtube.com")); add(blog(q)); add(youtube(q)); add(diningcode(q))
        time.sleep(0.3)
    for site in ("diningcode.com", "mangoplate.com", "siksinhot.com"):
        add(gnews("부산 맛집", site))
    H.log("srcs", ok, "cands", len(cands))
    src_n = lambda m: sum(1 for k in ("news", "blog", "youtube", "site") if m[k])
    ranked = sorted(cands.items(), key=lambda x: (-src_n(x[1]), -sum(x[1][k] for k in ("news", "blog", "youtube", "site"))))
    res, seen = [], set()
    for name, m in ranked[:160]:
        if src_n(m) < 2 or len(res) >= 20: continue
        if re.sub(r"\s+", "", name) in excl_nm: continue
        p = H.kakao_search_place(name)
        if not p or p["id"] in excl_id or p["id"] in seen or not FOODCATE.search(p["cate"]) : continue
        cn = re.sub(r"\s+", "", name); pn = re.sub(r"\s+", "", p["n"])
        if GENERIC.search(cn) or GENERIC.search(pn): continue
        if re.sub(r"\s+", "", p["n"]) in excl_nm: continue
        seen.add(p["id"])
        d = H.kakao_detail(p["id"]) or {}
        if (d.get("rc") or p["rc"] or 0) < 10: continue
        res.append({"id": p["id"], "n": p["n"], "gu": d.get("gu") or "", "c": (d.get("c") or p["cate"].split()[-1]),
                    "addr": d.get("addr") or p["addr"], "sc": d.get("sc") or p["sc"], "rc": d.get("rc") or p["rc"],
                    "im": d.get("im"), "ims": d.get("ims") or [],
                    "by": {k: m[k] for k in ("youtube", "blog", "news", "site")}, "mentions": sum(m[k] for k in ("youtube", "blog", "news", "site")),
                    "srcn": src_n(m), "sample": m["t"], "map": "https://place.map.kakao.com/" + p["id"]})
    res.sort(key=lambda r: (-r["srcn"], -r["mentions"], -(r["rc"] or 0)))
    now = datetime.datetime.now(H.KST).strftime("%Y-%m-%d %H:%M")
    json.dump({"updated": now, "basis": "기준: 2026.1~9 유튜브·블로그·뉴스·맛집사이트 언급 (2개 이상 출처, 카카오 검증, 기존 랭킹 제외)",
               "sources": ok, "places": res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    H.log("saved", len(res))

if __name__ == "__main__":
    main()
