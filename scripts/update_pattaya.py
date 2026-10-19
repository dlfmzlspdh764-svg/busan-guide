#!/usr/bin/env python3
"""파타야 TOP10 주간 갱신 (Google Maps 공개 검색 페이지, Playwright+Chrome).
- 카테고리별 영어·태국어 검색 → 리뷰 수 기준 이상만 → 베이지안 평점(+태국어 검색 노출 가산) 순위
- 상위 후보는 장소 페이지에서 영업시간·가격대·리뷰 키워드 수집
- 수집 실패(차단 등) 카테고리는 기존 pattaya.json 값 유지. 텔레그램 없음.
"""
import json, os, re, sys, time, math, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "pattaya.json")
KST = timezone(timedelta(hours=9))
BIGC = (12.9358, 100.8832)   # Big C Extra (North Pattaya / Central)
T21 = (12.9275, 100.8772)    # Terminal 21 Pattaya
CATS = [
 ("isan", "🌶 이싼(이산) 음식", 200, ["Isan restaurant Pattaya", "ร้านอาหารอีสาน พัทยา", "som tam restaurant Pattaya"], "food"),
 ("seafood", "🦐 씨푸드 뷔페", 200, ["seafood buffet Pattaya", "บุฟเฟ่ต์ทะเล พัทยา", "seafood buffet restaurant Pattaya Naklua"], "food"),
 ("korean", "🇰🇷 한식", 200, ["Korean restaurant Pattaya", "ร้านอาหารเกาหลี พัทยา", "Korean BBQ Pattaya"], "food"),
 ("mood", "🌅 분위기 좋은 식당", 200, ["romantic restaurant Pattaya", "rooftop restaurant Pattaya", "sea view restaurant Pattaya"], "food"),
 ("sights", "📍 가볼만한 곳", 200, ["tourist attractions Pattaya", "สถานที่ท่องเที่ยว พัทยา"], "sight"),
 ("massage", "💆 마사지 잘하는 곳", 100, ["massage Pattaya", "นวดแผนไทย พัทยา", "Thai massage spa Pattaya"], "massage"),
 ("etc", "🎡 기타 가볼만한 곳", 200, ["night market Pattaya", "cafe with view Pattaya", "show Pattaya cabaret", "viewpoint Pattaya"], "sight"),
]
EXCL = {
 "isan": re.compile(r"hotel|resort|massage", re.I),
 "seafood": re.compile(r"hotel(?!.*buffet)|massage", re.I),
 "korean": re.compile(r"massage|hotel|mart|shop|supermarket|church|clinic", re.I),
 "mood": re.compile(r"massage", re.I),
 "massage": re.compile(r"hotel|resort|school|academy|shop", re.I),
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
JS_LIST = """()=>[...document.querySelectorAll('div[role=feed] a.hfpxzc')].map(a=>{const c=a.parentElement;return {name:a.getAttribute('aria-label'),href:a.href,rating:(c.querySelector('.MW4etd')||{}).textContent||null,reviews:(c.querySelector('.UY7F9')||{}).textContent||null,text:c.innerText}})"""
JS_DET = """()=>{const L=[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label'));const m=document.querySelector('div[role=main]')||document.body;return {hours:L.filter(s=>/^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),/.test(s)),cat:(document.querySelector('button.DkEaL')||{}).textContent||'',addr:(document.querySelector('button[data-item-id=address]')||{}).ariaLabel||'',chips:[...document.querySelectorAll('button[aria-label][jsaction*=pane] .uEubGf, div.KNfEk .uEubGf')].map(e=>e.textContent).slice(0,8),txt:m.innerText.slice(0,4000)}}"""


def hav(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def fx_thb_krw():
    for url in ("https://open.er-api.com/v6/latest/THB", "https://api.frankfurter.app/latest?from=THB&to=KRW"):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=15))
            return float(d["rates"]["KRW"]), url.split("/")[2]
        except Exception:
            pass
    return 41.0, "fallback"


def num(s):
    s = (s or "").strip("() \u00a0").replace(",", "")
    m = re.match(r"([\d.]+)\s*([KkMm천만]?)", s)
    if not m:
        return 0
    v = float(m.group(1))
    return int(v * {"K": 1e3, "k": 1e3, "천": 1e3, "M": 1e6, "m": 1e6, "만": 1e4}.get(m.group(2), 1))


def pid(href):
    m = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", href or "")
    return m.group(1) if m else None


def coords(href):
    m = re.search(r"!3d(-?[\d.]+)!4d(-?[\d.]+)", href or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def area(ll):
    if not ll:
        return "파타야"
    la, lo = ll
    d = hav(ll, T21)
    if d > 9000:
        return "파타야 외곽"
    if la >= 12.945:
        return "북파타야·나클루아"
    if la >= 12.922:
        return "센트럴·세컨드로드"
    if la >= 12.900:
        return "남파타야·워킹스트리트·프라탐낙"
    return "좀티엔"


def thai(s):
    return bool(re.search(r"[\u0E00-\u0E7F]", s or ""))


def gopen(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    time.sleep(3.5)
    for s in ['button:has-text("Accept all")', 'button:has-text("모두 수락")']:
        try:
            page.locator(s).first.click(timeout=1200); time.sleep(2); break
        except Exception:
            pass


def search(page, q, hl="en"):
    gopen(page, "https://www.google.com/maps/search/" + urllib.parse.quote(q) + f"/@12.9276,100.8771,14z?hl={hl}&gl=th")
    for _ in range(7):
        try:
            page.locator("div[role=feed]").evaluate("e=>e.scrollBy(0,3000)")
        except Exception:
            break
        time.sleep(1.1)
    try:
        return page.evaluate(JS_LIST)
    except Exception:
        return []


def detail(page, href):
    sep = "&" if "?" in href else "?"
    gopen(page, re.sub(r"[?&]hl=[a-z-]+", "", href) + sep + "hl=en")
    try:
        return page.evaluate(JS_DET)
    except Exception:
        return {}


def parse_hours(hs):
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ko = dict(zip(order, "월화수목금토일"))
    d = {}
    for s in hs:
        p = s.split(",")
        if len(p) >= 2 and p[0] in ko:
            d[p[0]] = p[1].strip().replace("\u202f", " ")
    if not d:
        return ""
    vals = [d.get(k, "?") for k in order]
    if len(set(vals)) == 1:
        v = vals[0]
        return "매일 " + ("24시간" if "24" in v else v.replace(" to ", "~"))
    return " · ".join(f"{ko[k]} {d[k].replace(' to ', '~')}" for k in order if k in d)


def parse_price(txt):
    m = re.search(r"฿\s?([\d,]+)\s?[–-]\s?([\d,]+)", txt or "")
    if m:
        return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
    m = re.search(r"฿\s?([\d,]+)\+", txt or "")
    if m:
        return int(m.group(1).replace(",", "")), None
    return None


def chips(txt):
    # 'Reviews' section topic chips: "keyword\nN" lines after "All"
    m = re.search(r"\nAll\n(.*?)(?:\n\+\d+|\nWrite a review)", txt or "", re.S)
    if not m:
        return []
    lines = [l.strip() for l in m.group(1).split("\n") if l.strip()]
    out = []
    for i in range(0, len(lines) - 1, 2):
        if lines[i + 1].isdigit():
            out.append(lines[i])
    return out[:4]


def main():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("playwright missing — keep existing"); return
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
        except Exception:
            old = {}
    rate, fxsrc = fx_thb_krw()
    cats_out = {c["key"]: c for c in old.get("cats", [])}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-blink-features=AutomationControlled"])
        pg = b.new_page(locale="en-US", viewport={"width": 1280, "height": 900}, user_agent=UA)
        for key, label, minrev, qs, kind in CATS:
            pool = {}
            for q in qs:
                res = search(pg, q)
                print(key, q, len(res), flush=True)
                for r in res:
                    i = pid(r["href"]) or r["name"]
                    rv = num(r.get("reviews")); rt = float(r["rating"]) if r.get("rating") else 0
                    if i not in pool:
                        pool[i] = dict(r, id=i, rv=rv, rt=rt, thq=False)
                    if thai(q):
                        pool[i]["thq"] = True
            ex = EXCL.get(key)
            cand = []
            for x in pool.values():
                ll = coords(x["href"])
                if not ll or hav(ll, T21) > 25000 or x["rv"] < minrev or not x["rt"]:
                    continue
                if ex and ex.search(x["name"] + " " + x["text"].split("\n")[3 if len(x["text"].split("\n")) > 3 else 0]):
                    continue
                m = minrev
                x["bayes"] = (x["rt"] * x["rv"] + 4.3 * m) / (x["rv"] + m)
                x["local"] = bool(x["thq"] or thai(x["name"]))
                x["score"] = x["bayes"] + (0.03 if x["local"] else 0)
                x["ll"] = ll
                cand.append(x)
            cand.sort(key=lambda x: -x["score"])
            top = cand[:10]
            if len(top) < 5:
                print(key, "too few — keep old"); continue
            # Korean names via hl=ko search on place name
            items = []
            for n, x in enumerate(top, 1):
                d = detail(pg, x["href"])
                txt = d.get("txt", "")
                pr = parse_price(txt)
                ln = x["text"].split("\n")
                catline = ln[3] if len(ln) > 3 else ""
                plev = (re.search(r"(฿{1,4})(?!\s?\d)", catline) or [None, None])[1] if catline else None
                it = {
                    "rank": n, "name": x["name"], "rating": x["rt"], "reviews": x["rv"],
                    "type": (d.get("cat") or catline.split("·")[0]).strip(),
                    "area": area(x["ll"]), "lat": round(x["ll"][0], 6), "lon": round(x["ll"][1], 6),
                    "addr": (d.get("addr") or "").replace("Address: ", "").strip(),
                    "hours": parse_hours(d.get("hours", [])) or "정보 없음",
                    "price_thb": list(pr) if pr else None, "price_level": plev,
                    "keywords": chips(txt),
                    "local": x["local"],
                    "bigc_m": int(hav(x["ll"], BIGC)), "t21_m": int(hav(x["ll"], T21)),
                    "maps": "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(x["name"]) + "&query_place_id=" + urllib.parse.quote(x["id"]),
                    "maps_place": x["href"].split("?")[0],
                }
                if pr:
                    it["price_krw"] = [int(round(v * rate, -2)) if v else None for v in pr]
                items.append(it)
                print(" ", n, it["name"], it["rating"], it["reviews"], it["hours"][:40], pr, flush=True)
            # Korean names
            for it in items:
                try:
                    r = search(pg, it["name"], hl="ko")
                    gopen  # noqa
                    t = pg.evaluate("()=>{const h=document.querySelector('h1');return h?h.textContent:''}")
                    ko = (r[0]["name"] if r else t) or ""
                    if ko and re.search(r"[가-힣]", ko):
                        it["name_ko"] = ko
                except Exception:
                    pass
            old_ko = {i["name"]: i for i in cats_out.get(key, {}).get("items", [])}
            for it in items:
                o = old_ko.get(it["name"], {})
                for k in ("name_ko", "note"):
                    if o.get(k) and not it.get(k):
                        it[k] = o[k]
            cats_out[key] = {"key": key, "label": label, "min_reviews": minrev, "queries": qs, "items": items}
        b.close()
    hot = None
    try:
        hot = json.load(open(os.path.join(ROOT, "hotels_pattaya.json"))).get("updated")
    except Exception:
        pass
    data = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "source": "Google 지도 공개 검색·장소 페이지 (영어·태국어 검색)",
        "basis": "리뷰 수 기준 이상(음식·명소 200+, 마사지 100+)만, 평점×리뷰수 보정점수(베이지안, 기준 4.3) 순. 태국어 검색에도 노출된 곳은 '현지인 신호' 가산(+0.03). 실시간 방문자 수는 공개되지 않아 리뷰 수를 인기도로 사용.",
        "fx": {"thb_krw": round(rate, 2), "src": fxsrc},
        "landmarks": {"bigc": "Big C Extra", "t21": "Terminal 21"},
        "cats": [cats_out[c[0]] for c in CATS if c[0] in cats_out],
        "hotels_updated": hot,
    }
    json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("saved", OUT, [len(c["items"]) for c in data["cats"]])


if __name__ == "__main__":
    main()
