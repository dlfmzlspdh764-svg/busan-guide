#!/usr/bin/env python3
"""파타야 4성급 호텔 TOP10 주간 갱신 (Google Hotels 공개 검색).
- 대상: 북파타야·나클루아 / 세컨드·써드로드 (좀티언 제외)
- 평점·리뷰는 Playwright+Chrome이 있을 때만 재수집, 없으면 기존 유지 + USD→KRW 환율만 갱신
- 텔레그램 없음. stdlib + (optional) playwright
"""
import json, os, re, time, math, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "hotels_pattaya.json")
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
LAND = {
    "bigc_extra": (12.9358, 100.8832),
    "bigc_south": (12.9240, 100.8788),
    "terminal21": (12.9275, 100.8772),
    "central": (12.9349, 100.8827),
}
# Fixed candidate pool (4★ only). Scores refreshed when Playwright works.
CAND = [
    ("저니허브 파타야 센트럴", "Journeyhub Pattaya Central"),
    ("호텔 비스타 파타야", "Hotel Vista Pattaya"),
    ("더 베이뷰 호텔 파타야", "The Bayview Hotel Pattaya"),
    ("썬빔 호텔 파타야", "Sunbeam Hotel Pattaya"),
    ("LK 더 임프레스 파타야", "LK The Empress Pattaya"),
    ("아쿠아 호텔 파타야", "Aqua Hotel Pattaya"),
    ("인티메트 호텔 바이 팀 부티크", "Intimate Hotel by Team Boutique"),
    ("더 스테이 호텔 파타야", "The Stay Hotel Pattaya"),
    ("페이지 10 호텔", "Page Ten Hotel and Restaurant"),
    ("LK 메트로폴 파타야", "LK Metropole Pattaya"),
    ("골든 비치 호텔 파타야", "Golden Beach Hotel Pattaya"),
    ("선샤인 호텔 앤드 레지던스", "Sunshine Hotel and Residences"),
]


def fx_usd_krw():
    for url in (
        "https://open.er-api.com/v6/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=KRW",
    ):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=15))
            if "rates" in d and "KRW" in d["rates"]:
                return float(d["rates"]["KRW"]), url.split("/")[2]
        except Exception:
            pass
    return 1330.0, "fallback"


def hav(a, b):
    R = 6371000.0
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def walk_min(m):
    return max(1, int(round(m / 80.0)))


def scrape_google():
    """Return {name_en: {score, reviews, usd, breakfast}} or None if Playwright unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("playwright missing — FX-only refresh")
        return None
    out = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome", headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(
                locale="ko-KR", viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            # list page
            page.goto(
                "https://www.google.com/travel/search?q=Pattaya%204%20star%20hotels%20-Jomtien&hl=ko&gl=kr&curr=KRW",
                wait_until="domcontentloaded", timeout=90000,
            )
            time.sleep(4)
            for sel in ['button:has-text("동의합니다")', 'button:has-text("Accept all")']:
                try:
                    page.locator(sel).first.click(timeout=2000)
                    break
                except Exception:
                    pass
            for _ in range(8):
                page.mouse.wheel(0, 2200)
                time.sleep(0.8)
            text = page.inner_text("body")
            browser.close()
    except Exception as e:
        print("scrape fail", e)
        return None

    def grab(en, aliases):
        for key in aliases:
            idx = text.lower().find(key.lower())
            if idx < 0:
                continue
            chunk = text[idx : idx + 700]
            m = re.search(r"(\d\.\d)\s*\(([\d.,]+|\d+\.?\d*\s*천)\)", chunk)
            p = re.search(r"US\$(\d+)|₩([\d,]+)", chunk)
            if not m:
                continue
            rv = m.group(2).replace(",", "").replace(" ", "")
            reviews = int(float(rv.replace("천", "")) * 1000) if "천" in rv else int(float(rv))
            usd = None
            krw = None
            if p:
                if p.group(1):
                    usd = int(p.group(1))
                else:
                    krw = int(p.group(2).replace(",", ""))
            bf = "정보 없음"
            if "조식 포함" in chunk:
                bf = "조식 포함(표시)"
            elif "유료 조식" in chunk:
                bf = "유료 조식"
            elif "조식" in chunk:
                bf = "조식(별도/포함 확인)"
            return {"score": float(m.group(1)), "reviews": reviews, "usd": usd, "krw": krw, "breakfast": bf}
        return None

    alias = {
        "Journeyhub Pattaya Central": ["Journeyhub", "저니허브"],
        "Hotel Vista Pattaya": ["Hotel Vista", "비스타"],
        "The Bayview Hotel Pattaya": ["Bayview", "베이뷰"],
        "Sunbeam Hotel Pattaya": ["Sunbeam", "썬빔"],
        "LK The Empress Pattaya": ["LK The Empress", "임프레스", "더 임프레스"],
        "Aqua Hotel Pattaya": ["Aqua Hotel", "아쿠아"],
        "Intimate Hotel by Team Boutique": ["Intimate", "인티메트"],
        "The Stay Hotel Pattaya": ["The Stay", "더 스테이"],
        "Page Ten Hotel and Restaurant": ["Page Ten", "페이지 10", "페이지10"],
        "LK Metropole Pattaya": ["LK Metropole", "메트로폴"],
        "Golden Beach Hotel Pattaya": ["Golden Beach", "골든 비치"],
        "Sunshine Hotel and Residences": ["Sunshine Hotel", "선샤인"],
    }
    for _, en in CAND:
        g = grab(en, alias.get(en, [en]))
        if g:
            out[en] = g
            print("got", en, g)
    return out or None


def load_prev():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except Exception:
        return {"hotels": []}


def main():
    rate, provider = fx_usd_krw()
    prev = load_prev()
    scraped = scrape_google()
    hotels = []
    by_en = {h["name_en"]: h for h in prev.get("hotels", [])}
    for ko, en in CAND:
        base = dict(by_en.get(en) or {})
        if scraped and en in scraped:
            g = scraped[en]
            base["score"] = g["score"]
            base["reviews"] = g["reviews"]
            base["breakfast"] = g.get("breakfast") or base.get("breakfast") or "정보 없음"
            if g.get("usd"):
                base["price_usd"] = g["usd"]
            if g.get("krw"):
                base["price_krw"] = g["krw"]
                base["price_usd"] = int(round(g["krw"] / rate))
        if "price_usd" not in base and "price_krw" in base:
            base["price_usd"] = int(round(base["price_krw"] / rate))
        if "price_usd" in base:
            base["price_krw"] = int(round(base["price_usd"] * rate))
            base["price_basis"] = (
                f"1박·객실1실 Google 호텔 표시가(USD {base['price_usd']}) → KRW 환산"
                f"(환율 {rate:.2f}, {NOW.strftime('%Y-%m-%d')}, {provider}). "
                "세금/봉사료·조식 포함 여부는 예약 화면에서 최종 확인."
            )
        if not base.get("name"):
            base["name"] = ko
            base["name_en"] = en
        base.setdefault("stars", 4)
        base.setdefault("subs", {"청결": "정보 없음", "조식": "정보 없음", "위치": "정보 없음"})
        base.setdefault("photo", None)
        if base.get("reviews", 0) >= 500 and base.get("score"):
            hotels.append(base)
    hotels.sort(key=lambda h: (-float(h["score"]), -int(h["reviews"])))
    top = hotels[:10]
    for i, h in enumerate(top, 1):
        h["rank"] = i
    out = {
        "updated": NOW.strftime("%Y-%m-%d %H:%M"),
        "source": prev.get("source")
        or "Google 호텔(Google Hotels) 공개 검색 결과 + OpenStreetMap Nominatim 좌표",
        "fx": {"USD_KRW": rate, "as_of": NOW.strftime("%Y-%m-%d"), "provider": provider},
        "scope": prev.get("scope")
        or "파타야 4성급 · 북파타야/나클루아 · 세컨드·써드로드(중앙) · 좀티언 제외 · 리뷰≥500 · 평점순 TOP10",
        "note": prev.get("note")
        or "방콕(수완나품/돈므앙) 도착 후 파타야까지 차량·버스 약 2시간. 항공은 부산→방콕 직항 참고.",
        "hotels": top,
    }
    # keep distances from previous if present
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT, "n=", len(top), "fx", rate)


if __name__ == "__main__":
    main()
