#!/usr/bin/env python3
"""🔥 요즘 핫플 — 최근 7일 뉴스·블로그·유튜브 언급 집계 (틱톡 제외).
hot.json: places TOP 10 + 화제어 keywords(▲ vs 직전)."""
from __future__ import annotations
import datetime, html as H, json, os, re, ssl, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "hot.json")
FOOD = os.path.join(ROOT, "food.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
CTX = ssl.create_default_context()
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

GNEWS_QS = [
    "부산 맛집 when:7d",
    "부산 핫플 when:7d",
    "부산 카페 when:7d",
    "부산 돼지국밥 when:7d",
    "부산 돼지국밥 대전 when:7d",
    "부산 미슐랭 when:7d",
    "부산 맛집 site:youtube.com when:7d",
    "부산 핫플 site:youtube.com when:7d",
]
BLOG_QS = ["부산 맛집", "부산 핫플", "부산 카페 추천", "부산 돼지국밥"]
YT_QS = ["부산 맛집", "부산 핫플"]

STOP = {
    "부산", "맛집", "대구", "마작", "진짜", "전국", "국밥", "핫플", "카페", "추천", "여행", "관광", "데이트", "리뷰", "후기", "베스트",
    "요즘", "실시간", "가족", "외식", "명소", "인기", "최신", "오늘", "주말", "어디", "가게",
    "식당", "음식", "메뉴", "브이로그", "영상", "shorts", "Shorts", "버스안", "정보", "위치",
    "영업", "시간", "주차", "예약", "방문", "솔직", "후기모음", "총정리", "모음", "리스트",
    "TOP", "top", "근황", "개봉", "축제", "행사", "뉴스", "속보", "생활", "달인",
}
EXCLUDE_TITLE = re.compile(r"살인|폭행|화재|교통사고|사망|검거|피의자|성폭", re.I)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, tries=2, timeout=18, headers=None):
    last = None
    h = dict(UA)
    if headers:
        h.update(headers)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return H.unescape(re.sub(r"\s+", " ", s)).strip()


def clean_name(n):
    n = re.sub(r"\s*(본점|직영점|[가-힣A-Za-z0-9]{1,8}점)$", "", (n or "").strip())
    return n.strip()


def stems_for(n):
    """Match stems for a place name (longest first)."""
    out, seen = [], set()
    def add(s, minlen=3):
        s = (s or "").strip()
        if len(s) < minlen or s in seen or s in STOP:
            return
        seen.add(s)
        out.append(s)
    add(n)
    cn = clean_name(n)
    add(cn)
    if " " in cn:
        add(cn.split()[0])
    hang = re.sub(r"[^가-힣0-9A-Za-z]", "", cn)
    if len(hang) >= 4:
        add(hang)
        for L in (8, 7, 6, 5, 4):
            if len(hang) >= L:
                add(hang[:L])
    # short brand (2 chars) for 국밥/갈비/복국 상호 — matched carefully later
    if re.search(r"국밥|갈비|복국|막국수|밀면", hang) and len(hang) >= 4:
        add(hang[:2], minlen=2)
    out.sort(key=len, reverse=True)
    return out


def load_places():
    db = json.load(open(FOOD, encoding="utf-8")) if os.path.exists(FOOD) else {}
    items = []
    for key in ("food", "sushi", "chinese"):
        for p in db.get(key) or []:
            if p.get("n") and p.get("id"):
                items.append(p)
    return items, db


def parse_gnews(q):
    url = "https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko" % urllib.parse.quote(q)
    root = ET.fromstring(fetch(url))
    items = []
    for it in root.findall("./channel/item"):
        title = strip_html((it.findtext("title") or "").split(" - ")[0])
        if not title or EXCLUDE_TITLE.search(title):
            continue
        src = "youtube" if "youtube.com" in q else "news"
        items.append({"title": title, "src": src})
    return items


def parse_naver_blog(q):
    url = (
        "https://search.naver.com/search.naver?where=blog&query=%s&sm=tab_opt&nso=so%%3Add%%2Cp%%3A1w"
        % urllib.parse.quote(q)
    )
    try:
        raw = fetch(url, headers={"Referer": "https://search.naver.com/"}).decode("utf-8", "ignore")
    except Exception as e:
        log("naver fail", q, e)
        return []
    items, seen = [], set()
    # blog.naver.com anchor texts
    for m in re.finditer(r'href="https://blog\.naver\.com/[^"]+"[^>]*>(.*?)</a>', raw, re.S):
        title = strip_html(m.group(1))
        if len(title) < 8 or title in seen or "새 창" in title:
            continue
        seen.add(title)
        items.append({"title": title, "src": "blog"})
    # JSON-ish titles
    for m in re.finditer(r'"title"\s*:\s*"([^"]{8,100})"', raw):
        title = strip_html(m.group(1).encode("utf-8").decode("unicode_escape", "ignore") if "\\u" in m.group(1) else m.group(1))
        if len(title) < 8 or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "src": "blog"})
    return items[:50]


def parse_youtube(q):
    url = "https://www.youtube.com/results?search_query=%s" % urllib.parse.quote(q)
    try:
        raw = fetch(url).decode("utf-8", "ignore")
    except Exception as e:
        log("yt fail", q, e)
        return []
    items, seen = [], set()
    for m in re.finditer(r'"title":\{"runs":\[\{"text":"(.*?)"\}', raw):
        raw_t = m.group(1)
        try:
            title = bytes(raw_t, "utf-8").decode("unicode_escape")
        except Exception:
            title = raw_t
        title = title.replace("\\u0026", "&").replace('\\"', '"').strip()
        if len(title) < 6 or title in seen:
            continue
        if title in ("YouTube", "Home", "Subscriptions"):
            continue
        seen.add(title)
        items.append({"title": title, "src": "youtube"})
    return items[:40]


def build_index(places):
    """stem -> list of place ids (prefer longer stems assigned uniquely)."""
    # map stem -> best place (prefer higher review count)
    stem_map = {}
    for p in places:
        for s in stems_for(p["n"]):
            cur = stem_map.get(s)
            if not cur or (p.get("rc") or 0) > (cur.get("rc") or 0):
                stem_map[s] = p
    # sort stems longest first for matching
    stems = sorted(stem_map.keys(), key=len, reverse=True)
    return stems, stem_map


def match_title(title, stems, stem_map, max_n=4):
    found, used = [], set()
    t = title or ""
    for s in stems:
        if len(s) < 3:
            continue
        if s not in t:
            continue
        p = stem_map[s]
        if p["id"] in used:
            continue
        # avoid tiny stem matching inside longer unrelated words if stem < 4 and not boundary-ish
        if len(s) <= 2:
            # only quoted or punct-flanked short brands
            ok=False
            for m in re.finditer(re.escape(s), t):
                a,b=m.start(),m.end()
                left=t[a-1] if a>0 else " "
                right=t[b] if b<len(t) else " "
                if left in QUOTE_L and right in QUOTE_R:
                    ok=True; break
            if not ok: continue
            found.append(p); used.add(p["id"])
        elif len(s) < 4:
            for m in re.finditer(re.escape(s), t):
                a, b = m.start(), m.end()
                left = t[a - 1] if a > 0 else " "
                right = t[b] if b < len(t) else " "
                if re.match(r"[가-힣A-Za-z0-9]", left) or re.match(r"[가-힣A-Za-z0-9]", right):
                    continue
                found.append(p); used.add(p["id"]); break
        else:
            found.append(p); used.add(p["id"])
        if len(found) >= max_n:
            break
    return found


def keyword_rank(titles, top_places, stem_map):
    counts = {}
    for t in titles:
        # known place stems present
        for s, p in stem_map.items():
            if len(s) >= 3 and s in t:
                k = clean_name(p["n"]) or p["n"]
                counts[k] = counts.get(k, 0) + 1
        # X 맛집 / X 카페 patterns
        for m in re.finditer(r"([가-힣A-Za-z0-9]{2,12})\s*(?:맛집|카페|핫플)", t):
            w = m.group(1)
            if w in STOP or w.isdigit() or len(w)<2 or w in ("진짜","전국","블루","캐치","생활","달인","진행","화면","시작"):
                continue
            counts[w] = counts.get(w, 0) + 1
    # boost top places
    for p in top_places:
        k = clean_name(p["n"]) or p["n"]
        counts[k] = max(counts.get(k, 0), p["mentions"])
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    out = []
    seen = set()
    for k, v in ranked:
        if k in seen or k in STOP or v < 1:
            continue
        seen.add(k)
        out.append((k, int(v)))
        if len(out) >= 10:
            break
    return out


def main():
    now = datetime.datetime.now(KST)
    places, _ = load_places()
    stems, stem_map = build_index(places)
    place_by_id = {p["id"]: p for p in places}

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            prev = {}
    prev_kw = {k["k"]: k.get("n", 0) for k in (prev.get("keywords") or []) if k.get("k")}
    prev_place = {p["id"]: p.get("mentions", 0) for p in (prev.get("places") or []) if p.get("id")}

    mentions = {}
    all_titles = []
    src_ok = {"news": 0, "blog": 0, "youtube": 0}

    for q in GNEWS_QS:
        try:
            items = parse_gnews(q)
            for it in items:
                src_ok[it["src"]] = src_ok.get(it["src"], 0) + 1
                all_titles.append(it["title"])
                for p in match_title(it["title"], stems, stem_map):
                    m = mentions.setdefault(p["id"], {"news": 0, "blog": 0, "youtube": 0, "titles": []})
                    m[it["src"]] += 1
                    if len(m["titles"]) < 3:
                        m["titles"].append(it["title"][:90])
            time.sleep(0.25)
        except Exception as e:
            log("gnews", q, e)

    for q in BLOG_QS:
        items = parse_naver_blog(q)
        src_ok["blog"] += len(items)
        for it in items:
            all_titles.append(it["title"])
            if "부산" not in it["title"] and "Busan" not in it["title"]:
                continue
            for p in match_title(it["title"], stems, stem_map):
                m = mentions.setdefault(p["id"], {"news": 0, "blog": 0, "youtube": 0, "titles": []})
                m["blog"] += 1
                if len(m["titles"]) < 3:
                    m["titles"].append(it["title"][:90])
        time.sleep(0.35)

    for q in YT_QS:
        items = parse_youtube(q)
        src_ok["youtube"] += len(items)
        for it in items:
            all_titles.append(it["title"])
            if "부산" not in it["title"] and "Busan" not in it["title"] and "busan" not in it["title"].lower():
                continue
            for p in match_title(it["title"], stems, stem_map):
                m = mentions.setdefault(p["id"], {"news": 0, "blog": 0, "youtube": 0, "titles": []})
                m["youtube"] += 1
                if len(m["titles"]) < 3:
                    m["titles"].append(it["title"][:90])
        time.sleep(0.4)

    ranked = []
    for pid, m in mentions.items():
        total = m["news"] + m["blog"] + m["youtube"]
        if total < 1:
            continue
        p = place_by_id.get(pid)
        if not p:
            continue
        ranked.append({
            "id": pid,
            "n": p["n"],
            "gu": p.get("gu") or p.get("a") or "",
            "c": p.get("c") or "",
            "addr": p.get("addr") or "",
            "sc": p.get("sc"),
            "rc": p.get("rc"),
            "im": p.get("im"),
            "ims": (p.get("ims") or [])[:5],
            "mentions": total,
            "by": {"news": m["news"], "blog": m["blog"], "youtube": m["youtube"]},
            "delta": total - prev_place.get(pid, 0),
            "sample": m["titles"][:2],
            "map": "https://map.kakao.com/?q=" + urllib.parse.quote(p["n"]),
        })
    ranked.sort(key=lambda x: (-x["mentions"], -(x.get("rc") or 0)))
    # collapse same clean_name keeping best
    top, seen = [], set()
    for p in ranked:
        k = clean_name(p["n"])
        if k in seen:
            continue
        seen.add(k)
        top.append(p)
        if len(top) >= 10:
            break

    kws = keyword_rank(all_titles, top, stem_map)
    keywords = []
    for k, v in kws:
        prev_n = prev_kw.get(k, 0)
        ch = v - prev_n
        keywords.append({"k": k, "n": v, "ch": ch, "arrow": "▲" if ch > 0 else ("▼" if ch < 0 else "–")})

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "basis": "뉴스·블로그·유튜브 최근 7일 언급 수 (틱톡은 로그인 필요로 제외)",
        "sources": src_ok,
        "places": top,
        "keywords": keywords,
    }

    if len(top) < 3 and (prev.get("places") or []):
        log("too few (%d), keep previous places" % len(top))
        out["places"] = prev["places"]
        out["note"] = "이번 수집 매칭 부족 → 직전 순위 유지"

    open(OUT, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))
    log("hot", len(out["places"]), "kw", len(keywords), "srcs", src_ok, "titles", len(all_titles))
    for i, p in enumerate(out["places"][:5], 1):
        log(i, p["n"], p["mentions"], p.get("by"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL", e)
        sys.exit(1)
