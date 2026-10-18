"""부산(PUS) 출발 태국·베트남 직항 왕복 최저가 수집 (Google Flights 공개 검색 결과).
매시간 실행, 날짜를 4개 슬롯으로 나눠 순환 조회 → 약 4시간마다 전 구간 갱신."""
import json, os, statistics, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from selectolax.lexbor import LexborHTMLParser
from fast_flights import create_query, FlightQuery, Passengers, fetch_flights_html

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.date()
NIGHTS = [3, 4, 5]
DAYS = range(3, 91)          # 출발일: D+3 ~ D+90
SLOTS = 4
CITY = {"BKK": ("태국", "방콕 수완나품"), "DMK": ("태국", "방콕 돈므앙"), "CNX": ("태국", "치앙마이"),
        "HKT": ("태국", "푸껫"), "USM": ("태국", "코사무이"), "KBV": ("태국", "끄라비"), "HDY": ("태국", "핫야이"), "UTP": ("태국", "파타야(우타파오)"),
        "DAD": ("베트남", "다낭"), "CXR": ("베트남", "나트랑(깜라인)"), "PQC": ("베트남", "푸꾸옥"), "HAN": ("베트남", "하노이"),
        "SGN": ("베트남", "호치민"), "DLI": ("베트남", "달랏"), "HPH": ("베트남", "하이퐁"), "VCA": ("베트남", "껀터"),
        "HUI": ("베트남", "후에"), "VII": ("베트남", "빈"), "UIH": ("베트남", "꾸이년"), "BMV": ("베트남", "부온마투옷"),
        "VDO": ("베트남", "하롱(번돈)"), "VCL": ("베트남", "쭈라이"), "THD": ("베트남", "타인호아"), "VCS": ("베트남", "꼰다오")}
BASE = ["BKK", "CNX", "DAD", "CXR", "PQC", "HAN", "SGN"]
ROUTES_F = "data/flight_routes.json"; ALERT_F = "data/flight_alerted.json"; OUT = "flights.json"


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def query(dest, d1, d2):
    return create_query(flights=[FlightQuery(date=d1, from_airport="PUS", to_airport=dest),
                                 FlightQuery(date=d2, from_airport=dest, to_airport="PUS")],
                        trip="round-trip", passengers=Passengers(adults=1), language="ko", currency="KRW", max_stops=0)


def search(dest, d1, d2):
    """직항 옵션 목록 반환. None = 조회 실패."""
    q = query(dest, d1, d2)
    for attempt in range(2):
        try:
            html = fetch_flights_html(q)
            sc = LexborHTMLParser(html).css_first(r"script.ds\:1")
            if not sc:
                raise RuntimeError("no data")
            raw = sc.text().split("data:", 1)[1].rsplit(",", 1)[0]
            if raw.endswith("errorHasStatus: true"):
                return []
            p = json.loads(raw)
            out = []
            for blk in (p[2], p[3]):
                for k in ((blk or [None])[0] or []):
                    f = k[0]
                    legs = f[2]
                    if len(legs) != 1:
                        continue
                    s = legs[0]
                    price = None
                    try:
                        price = k[1][0][1]
                    except Exception:
                        pass
                    t = lambda v: "%02d:%02d" % ((v or [0])[0] or 0, ((v or [0, 0]) + [0])[1] or 0) if v is not None else ""
                    fn = s[22] if len(s) > 22 and s[22] else None
                    out.append({"p": price, "al": (f[1] or [""])[0], "fn": (fn[0] + fn[1]) if fn else "",
                                "dt": t(s[8]), "at": t(s[10]), "ad": "%04d-%02d-%02d" % tuple(s[21]) if s[21] else d1,
                                "dur": s[11], "pl": s[17] or ""})
            seen = set(); uniq = []
            for o in sorted(out, key=lambda o: (o["p"] is None, o["p"] or 0)):
                key = (o["fn"], o["dt"])
                if key in seen:
                    continue
                seen.add(key); uniq.append(o)
            return uniq
        except Exception as e:
            err = e
            time.sleep(2)
    print("fail", dest, d1, err)
    return None


def tg(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("telegram skip"); return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=20).read()
    except Exception as e:
        print("telegram error", type(e).__name__)


def won(n):
    return "{:,}원".format(n)


def main():
    known = load(ROUTES_F, {"routes": [], "checked": None})
    prev = load(OUT, {"routes": {}})
    first_run = not prev.get("routes")
    # --- 신규 노선 탐색: 하루 1번(04시대) 또는 최초 ---
    new_routes = []
    if not known.get("checked") or NOW.hour == 4 or os.environ.get("FORCE_DISCOVER"):
        probe_dates = [TODAY + timedelta(days=d) for d in (14, 35, 60, 85)]
        jobs = [(c, d) for c in CITY for d in probe_dates]
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda a: (a[0], search(a[0], a[1].isoformat(), (a[1] + timedelta(days=4)).isoformat())), jobs))
        found = sorted({c for c, r in res if r})
        failed_all = all(r is None for _, r in res)
        if not failed_all:
            had = set(known.get("routes") or [])
            new_routes = [c for c in found if had and c not in had]
            known = {"routes": sorted(had | set(found)), "active": found, "checked": NOW.strftime("%Y-%m-%d %H:%M")}
            json.dump(known, open(ROUTES_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    routes = sorted(set(BASE) | set(known.get("routes") or []), key=lambda c: (CITY[c][0] != "태국", list(CITY).index(c)))
    # --- 요금 조회 (슬롯 순환, 최초 실행은 전체) ---
    slot = NOW.hour % SLOTS
    data = {c: {e["k"]: e for e in prev.get("routes", {}).get(c, {}).get("fares", []) if e["d"] >= (TODAY + timedelta(days=1)).isoformat()} for c in routes}
    jobs = []
    for c in routes:
        for i in DAYS:
            if not first_run and i % SLOTS != slot and (TODAY + timedelta(days=i)).isoformat() + "|3" in data[c]:
                continue
            for n in NIGHTS:
                d1 = TODAY + timedelta(days=i)
                jobs.append((c, d1.isoformat(), (d1 + timedelta(days=n)).isoformat(), n))
    print("queries", len(jobs))
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: (j, search(j[0], j[1], j[2])), jobs))
    ok = 0
    for (c, d1, d2, n), r in res:
        if r is None:
            continue
        ok += 1
        k = "%s|%d" % (d1, n)
        if not r:
            data[c].pop(k, None); continue
        data[c][k] = {"k": k, "d": d1, "r": d2, "n": n, "p": r[0]["p"], "o": r[:3], "chk": NOW.strftime("%m-%d %H:%M")}
    if jobs and ok < len(jobs) * 0.3:
        raise SystemExit("too many failures: %d/%d" % (ok, len(jobs)))
    # --- 결과 정리 ---
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M"), "source": "Google 항공편(Google Flights) 공개 검색 결과",
           "basis": "왕복·성인 1인·일반석·직항, 세금·유류할증료 포함 총액(KRW)", "window": "출발 D+3~D+90, 3·4·5박", "routes": {}}
    alerted = load(ALERT_F, {})
    deals = []
    for c in routes:
        fares = sorted(data[c].values(), key=lambda e: (e["p"] is None, e["p"] or 0, e["d"]))
        prices = [e["p"] for e in fares if e["p"]]
        med = int(statistics.median(prices)) if prices else None
        pr = prev.get("routes", {}).get(c, {})
        low_hist = min([x for x in (pr.get("low_hist"), prices[0] if prices else None) if x] or [0]) or None
        out["routes"][c] = {"country": CITY[c][0], "city": CITY[c][1], "fares": fares, "median": med, "min": prices[0] if prices else None,
                            "low_hist": low_hist, "airlines": sorted({o["al"] for e in fares for o in e["o"]})}
        if first_run or not med:
            continue
        for e in fares[:5]:
            if not e["p"]:
                continue
            key = c + "|" + e["k"]
            hot = e["p"] <= med * 0.8 or (pr.get("low_hist") and e["p"] < pr["low_hist"])
            last = alerted.get(key)
            if hot and (not last or e["p"] <= last * 0.95):
                alerted[key] = e["p"]
                deals.append((c, e, med, pr.get("low_hist")))
    alerted = {k: v for k, v in alerted.items() if k.split("|")[1] >= TODAY.isoformat()}
    json.dump(alerted, open(ALERT_F, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("routes", {c: (len(v["fares"]), v["min"]) for c, v in out["routes"].items()})
    # --- 텔레그램 ---
    app = "https://dlfmzlspdh764-svg.github.io/busan-guide/#flight"
    if deals:
        deals.sort(key=lambda x: x[1]["p"] / x[2])
        lines = ["🔥 항공 특가 (부산 출발 직항·왕복 1인, 세금·유류할증료 포함)"]
        for c, e, med, lh in deals[:6]:
            o = e["o"][0]
            tag = "역대 최저" if lh and e["p"] < lh else "평균 대비 %d%%↓" % round((1 - e["p"] / med) * 100)
            lines.append("\n✈️ 부산→%s %s\n%s ~ %s (%d박) · %s %s %s\n💰 %s (%s, 중간값 %s)\n%s" % (
                CITY[c][1], c, e["d"], e["r"], e["n"], o["al"], o["fn"], o["dt"], won(e["p"]), tag, won(med), query(c, e["d"], e["r"]).url()))
        lines.append("\n앱: " + app)
        tg("\n".join(lines))
    for c in new_routes:
        f = out["routes"].get(c, {})
        tg("🆕 부산발 신규 직항\n✈️ 김해(PUS) → %s(%s) · %s\n항공사: %s\n최저 왕복: %s\n앱: %s" % (
            CITY[c][1], c, CITY[c][0], ", ".join(f.get("airlines") or []) or "확인 중", won(f["min"]) if f.get("min") else "요금 미공개", app))


if __name__ == "__main__":
    main()
