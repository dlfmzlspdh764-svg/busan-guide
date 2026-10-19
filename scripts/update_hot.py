#!/usr/bin/env python3
"""🔥 요즘 핫플 — 발견형(discovery)
최근 7일 뉴스·블로그·유튜브에서 상호 후보를 뽑고,
카카오 검색으로 부산 실존 장소(카페/팝업/바/관광/맛집 등)인지 검증한 뒤
언급 수 TOP 10 + 화제어. food.json에 없어도 OK.
카카오 상세(평점·리뷰·사진)는 Actions에서 동작."""
from __future__ import annotations
import datetime, html as H, json, os, re, ssl, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "hot.json")
FOOD = os.path.join(ROOT, "food.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
CTX = ssl.create_default_context()
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
HS = {"Referer": "https://map.kakao.com/", "User-Agent": UA["User-Agent"]}
HP = {"Referer": "https://place.map.kakao.com/", "pf": "web", "User-Agent": UA["User-Agent"], "Accept": "application/json"}

QUERIES = [
    "부산 핫플", "부산 신상 카페", "부산 팝업", "부산 요즘 뜨는",
    "서면 핫플", "전포 핫플", "광안리 핫플", "해리단길 핫플", "영도 핫플",
    "부산 카페 신상", "부산 핫플레이스", "전포동 카페", "영도 카페",
]
GNEWS_EXTRA = [q + " when:7d" for q in QUERIES] + [
    "부산 핫플 site:youtube.com when:7d",
    "부산 신상 카페 site:youtube.com when:7d",
]

STOP = {
    "부산", "맛집", "핫플", "카페", "추천", "여행", "관광", "데이트", "리뷰", "후기", "베스트",
    "요즘", "실시간", "가족", "외식", "명소", "인기", "최신", "오늘", "주말", "어디", "가게",
    "식당", "음식", "메뉴", "브이로그", "영상", "정보", "위치", "영업", "시간", "주차", "예약",
    "방문", "총정리", "모음", "리스트", "근황", "축제", "행사", "뉴스", "속보", "생활", "달인",
    "대구", "서울", "인천", "광주", "대전", "울산", "제주", "진짜", "전국", "여기", "거기",
    "신상", "오픈", "오픈런", "웨이팅", "인스타", "틱톡", "유튜브", "shorts", "Shorts",
    "전포", "서면", "광안리", "해리단길", "영도", "해운대", "기장", "남포", "자갈치", "센텀",
    "핫플레이스", "플레이스", "팝업", "스토어", "전시", "갤러리", "마켓", "플리마켓",
    "뜨는", "핫한", "요즘뜨는", "필수", "코스", "일정", "주말코스", "당일치기",
}
EXCLUDE_TITLE = re.compile(r"살인|폭행|화재|교통사고|사망|검거|피의자|성폭|부고", re.I)
# quoted / titled candidate extractors
RE_QUOTED = re.compile(r"[‘'\"“]([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s&·\-]{1,20})[’'\"”]")
RE_NAMED = re.compile(
    r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9&·\-]{1,16})"
    r"(?:\s*(?:카페|맛집|핫플|베이커리|빵집|바|펍|갤러리|전시|팝업|스토어|식당|레스토랑|브런치))"
)
RE_HASH = re.compile(r"#([가-힣A-Za-z0-9]{2,16})")
ALLOW_CATE = re.compile(
    r"음식점|카페|디저트|베이커리|술집|바$|클럽|갤러리|전시|박물관|관광|명소|문화|테마파크|"
    r"쇼핑|시장|공원|해변|산책|복합문화|공방|서점|팝업|라이프스타일|숙박|호텔|베이커리|빵|"
    r"육류|한식|중식|일식|양식|아시아|패스트푸드|분식|치킨|피자|뷔페|횟집|해물"
)
DENY_CATE = re.compile(
    r"세무|회계|법무|병원|의원|약국|학원|학교|은행|보험|부동산|미용실|헤어|네일|헬스|피트니스|"
    r"골프|세탁|수리|기업|협회|시청|구청|경찰|소방|우체국|주차장|주유소|아파트|오피스텔|"
    r"페스티벌$|축제$|챌린지$|행사$"
)
CHAIN = re.compile(
    r"스타벅스|투썸|이디야|메가커피|컴포즈|빽다방|맥도날드|버거킹|롯데리아|CU|GS25|세븐일레븐|"
    r"다이소|무신사|올리브영|다이킹|배스킨|설빙|공차|엽기떡볶이|신전떡볶이"
)


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
            time.sleep(1.0 * (i + 1))
    raise last


def jget(url, h, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=18))
        except Exception:
            time.sleep(1.2 + i)
    return None


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return H.unescape(re.sub(r"\s+", " ", s)).strip()


def clean_cand(n):
    n = strip_html(n)
    n = re.sub(r"\s+", " ", n).strip(" ·\-–—|/")
    n = re.sub(r"^(카페|맛집|핫플)\s*", "", n)
    n = re.sub(r"\s*(카페|맛집|핫플|본점)$", "", n)
    if len(n) < 2 or len(n) > 24:
        return ""
    if n in STOP or n.isdigit() or CHAIN.search(n):
        return ""
    if re.fullmatch(r"[0-9A-Za-z\s]+", n) and len(n) < 4:
        return ""
    if re.search(r"제\d+회|챌린지|페스티벌|축제|대회|워크숍|설명회", n):
        return ""
    if len(n) > 16 and ("부산" in n or "국제" in n):
        return ""
    return n


def extract_candidates(title):
    found = []
    t = title or ""
    for rx in (RE_QUOTED, RE_NAMED):
        for m in rx.finditer(t):
            c = clean_cand(m.group(1))
            if c:
                found.append(c)
    for m in RE_HASH.finditer(t):
        c = clean_cand(m.group(1))
        if c and not c.startswith("부산"):
            found.append(c)
    # "OO에서" / "OO 방문"
    for m in re.finditer(r"([가-힣A-Za-z0-9]{2,14})\s*(?:에서|방문|다녀|추천|오픈)", t):
        c = clean_cand(m.group(1))
        if c:
            found.append(c)
    # dedupe preserve order
    out, seen = [], set()
    for c in found:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


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
        log("blog fail", q, e)
        return []
    items, seen = [], set()
    for m in re.finditer(r'href="https://blog\.naver\.com/[^"]+"[^>]*>(.*?)</a>', raw, re.S):
        title = strip_html(m.group(1))
        if len(title) < 8 or title in seen or "새 창" in title:
            continue
        seen.add(title)
        items.append({"title": title, "src": "blog"})
    for m in re.finditer(r'"title"\s*:\s*"([^"]{8,100})"', raw):
        raw_t = m.group(1)
        title = strip_html(raw_t.encode("utf-8").decode("unicode_escape", "ignore") if "\\u" in raw_t else raw_t)
        if len(title) < 8 or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "src": "blog"})
    return items[:40]


def parse_naver_news(q):
    url = (
        "https://search.naver.com/search.naver?where=news&query=%s&sm=tab_opt&sort=1&nso=so%%3Add%%2Cp%%3A1w"
        % urllib.parse.quote(q)
    )
    try:
        raw = fetch(url, headers={"Referer": "https://search.naver.com/"}).decode("utf-8", "ignore")
    except Exception as e:
        log("news fail", q, e)
        return []
    items, seen = [], set()
    for m in re.finditer(r'<a[^>]+class="[^"]*news_tit[^"]*"[^>]*>(.*?)</a>', raw, re.S):
        title = strip_html(m.group(1))
        if len(title) < 6 or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "src": "news"})
    if not items:
        for m in re.finditer(r'data-heatmap-target=["\'][^"\']*["\'][^>]*>([^<]{8,80})<', raw):
            title = strip_html(m.group(1))
            if title and title not in seen:
                seen.add(title)
                items.append({"title": title, "src": "news"})
    return items[:30]


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
        if len(title) < 6 or title in seen or title in ("YouTube", "Home"):
            continue
        if not re.search(r"부산|서면|전포|광안리|해리단길|영도|해운대|기장|남포", title):
            continue
        seen.add(title)
        items.append({"title": title, "src": "youtube"})
    return items[:35]


def kakao_search_place(name):
    """Validate candidate is a real Busan place. Returns best place dict or None."""
    for q in (f"부산 {name}", name):
        j = jget(
            "https://search.map.kakao.com/mapsearch/map.daum?callback=&q=%s&msFlag=A&sort=0&page=1"
            % urllib.parse.quote(q),
            HS,
        )
        time.sleep(0.2)
        if not j:
            continue
        for x in j.get("place") or []:
            if not isinstance(x, dict):
                continue
            addr = x.get("address") or ""
            if not addr.startswith("부산"):
                continue
            pname = x.get("name") or ""
            if not pname or CHAIN.search(pname):
                continue
            # name relevance: candidate appears in place name or vice versa
            cn = re.sub(r"\s+", "", name)
            pn = re.sub(r"\s+", "", pname)
            if cn not in pn and pn[: max(2, min(6, len(pn)))] not in cn and name not in pname:
                # soft: allow if query was exact and first result
                if q != f"부산 {name}":
                    continue
            pid = str(x.get("confirmid") or "")
            if not pid:
                continue
            cate = " ".join(x.get(k) or "" for k in ("cate_name_depth1", "cate_name_depth2", "cate_name_depth3", "cate_name_depth4"))
            if DENY_CATE.search(cate) or DENY_CATE.search(pname):
                continue
            if not ALLOW_CATE.search(cate) and not ALLOW_CATE.search(pname):
                # allow depth1 여행/문화시설/가정,생활 broadly if touristy words
                d1 = x.get("cate_name_depth1") or ""
                if d1 not in ("여행", "문화시설", "가정,생활", "서비스,산업"):
                    continue
            return {
                "id": pid,
                "n": pname,
                "addr": addr,
                "cate": cate,
                "rc": int(x.get("rating_count") or 0),
                "sc": float(x.get("rating_average") or x.get("rating") or 0) or None,
            }
    return None


def kakao_detail(pid):
    d = jget("https://place-api.map.kakao.com/places/panel3/" + pid, HP)
    time.sleep(0.2)
    if not d or not d.get("summary"):
        return None
    s = d["summary"]
    review = d.get("review") or {}
    rc = int(review.get("score_count") or review.get("count") or 0)
    sc = float(review.get("score") or review.get("star_rating") or 0) or None
    imgs = []
    seen = set()
    for x in ((d.get("photos") or {}).get("photos") or []):
        if x.get("media_type", "PHOTO") != "PHOTO":
            continue
        u = (x.get("url") or "").replace("http:", "https:")
        if u and "kakaocdn" in u and u not in seen:
            seen.add(u)
            imgs.append(u)
        if len(imgs) >= 5:
            break
    addr = ""
    a = s.get("address") or {}
    if isinstance(a, dict):
        addr = a.get("road") or a.get("jibun") or ""
    gu = ""
    for g in ["해운대구","부산진구","수영구","동래구","남구","중구","연제구","금정구","북구","사상구","사하구","동구","서구","영도구","강서구","기장군"]:
        if g in (addr or ""):
            gu = g
            break
    cate = ((s.get("category") or {}).get("name") if isinstance(s.get("category"), dict) else "") or ""
    return {
        "sc": sc, "rc": rc, "im": imgs[0] if imgs else None, "ims": imgs,
        "addr": addr or None, "gu": gu, "c": cate, "tel": s.get("phone") or "",
    }


def food_lookup():
    """Optional enrich from food.json by id/name."""
    if not os.path.exists(FOOD):
        return {}, {}
    db = json.load(open(FOOD, encoding="utf-8"))
    by_id, by_name = {}, {}
    for key in ("food", "sushi", "chinese"):
        for p in db.get(key) or []:
            by_id[str(p["id"])] = p
            by_name[re.sub(r"\s+", "", p["n"])] = p
    return by_id, by_name


def main():
    now = datetime.datetime.now(KST)
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            prev = {}
    prev_kw = {k["k"]: k.get("n", 0) for k in (prev.get("keywords") or []) if k.get("k")}

    all_titles = []
    src_ok = {"news": 0, "blog": 0, "youtube": 0}
    # cand -> {news,blog,youtube,titles,raw}
    cands = {}

    def add_items(items):
        for it in items:
            src = it["src"]
            src_ok[src] = src_ok.get(src, 0) + 1
            title = it["title"]
            all_titles.append(title)
            for name in extract_candidates(title):
                m = cands.setdefault(name, {"news": 0, "blog": 0, "youtube": 0, "titles": [], "raw": name})
                m[src] += 1
                if len(m["titles"]) < 3 and title not in m["titles"]:
                    m["titles"].append(title[:100])

    # Google News
    for q in GNEWS_EXTRA:
        try:
            add_items(parse_gnews(q))
            time.sleep(0.2)
        except Exception as e:
            log("gnews", q, e)

    # Naver blog + news (subset of queries to stay light)
    for q in QUERIES[:8]:
        add_items(parse_naver_blog(q))
        time.sleep(0.3)
        add_items(parse_naver_news(q))
        time.sleep(0.25)

    # YouTube
    for q in ["부산 핫플", "부산 신상 카페", "전포 핫플", "영도 핫플", "해리단길 핫플"]:
        add_items(parse_youtube(q))
        time.sleep(0.35)

    # rank candidates by raw mention before kakao
    ranked_c = sorted(cands.items(), key=lambda x: -(x[1]["news"] + x[1]["blog"] + x[1]["youtube"]))
    # prefer multi-source / multi-mention first
    ranked_c = sorted(
        ranked_c,
        key=lambda x: (
            -((x[1]["news"] > 0) + (x[1]["blog"] > 0) + (x[1]["youtube"] > 0)),
            -(x[1]["news"] + x[1]["blog"] + x[1]["youtube"]),
        ),
    )
    log("raw candidates", len(ranked_c), "titles", len(all_titles), "srcs", src_ok)

    # Kakao validate top N candidates
    TOP_TRY = 55
    validated = []  # list of place dicts with mentions
    seen_ids = set()
    food_by_id, food_by_name = food_lookup()

    for name, m in ranked_c[:TOP_TRY]:
        total = m["news"] + m["blog"] + m["youtube"]
        if total < 1:
            continue
        place = None
        # try food.json name hit first (fast)
        key = re.sub(r"\s+", "", name)
        if key in food_by_name:
            p = food_by_name[key]
            place = {"id": str(p["id"]), "n": p["n"], "addr": p.get("addr") or "", "cate": p.get("kc") or p.get("c") or "", "rc": p.get("rc") or 0, "sc": p.get("sc"), "from": "food"}
        if not place:
            place = kakao_search_place(name)
            if place:
                place["from"] = "kakao"
        if not place:
            continue
        pid = place["id"]
        if pid in seen_ids:
            # merge mentions into existing
            for v in validated:
                if v["id"] == pid:
                    v["mentions"] += total
                    v["by"]["news"] += m["news"]
                    v["by"]["blog"] += m["blog"]
                    v["by"]["youtube"] += m["youtube"]
                    for t in m["titles"]:
                        if t not in v["sample"] and len(v["sample"]) < 2:
                            v["sample"].append(t)
                    break
            continue
        seen_ids.add(pid)
        validated.append({
            "id": pid,
            "n": place["n"],
            "cand": name,
            "addr": place.get("addr") or "",
            "cate": place.get("cate") or "",
            "mentions": total,
            "by": {"news": m["news"], "blog": m["blog"], "youtube": m["youtube"]},
            "sample": m["titles"][:2],
            "sc": place.get("sc"),
            "rc": place.get("rc") or 0,
            "from": place.get("from"),
        })
        if len(validated) >= 16:
            break
        log("ok", name, "→", place["n"], total)

    # enrich details for top places (Kakao panel)
    need = [v["id"] for v in validated[:12]]
    details = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        def one(i):
            return i, kakao_detail(i)
        for pid, d in ex.map(one, need):
            if d:
                details[pid] = d

    places = []
    for v in validated:
        d = details.get(v["id"]) or {}
        fp = food_by_id.get(v["id"])
        gu = d.get("gu") or ""
        if not gu and v.get("addr"):
            for g in ["해운대구","부산진구","수영구","동래구","남구","중구","연제구","금정구","북구","사상구","사하구","동구","서구","영도구","강서구","기장군"]:
                if g in v["addr"]:
                    gu = g
                    break
        ims = d.get("ims") or ((fp.get("ims") if fp else None) or [])
        im = d.get("im") or (fp.get("im") if fp else None) or (ims[0] if ims else None)
        sc = d.get("sc") if d.get("sc") is not None else (v.get("sc") or (fp.get("sc") if fp else None))
        rc = d.get("rc") or v.get("rc") or (fp.get("rc") if fp else 0)
        c = d.get("c") or v.get("cate") or (fp.get("c") if fp else "")
        # simplify category label
        cl = "카페" if "카페" in c else ("맛집" if "음식" in c or "음식점" in c else (c.split(">")[-1].strip() if c else "장소"))
        places.append({
            "id": v["id"],
            "n": v["n"],
            "gu": gu or (fp.get("gu") if fp else "") or "",
            "c": cl,
            "addr": d.get("addr") or v.get("addr") or (fp.get("addr") if fp else "") or "",
            "sc": sc,
            "rc": rc,
            "im": im,
            "ims": (ims or ([im] if im else []))[:5],
            "mentions": v["mentions"],
            "by": v["by"],
            "sample": v["sample"],
            "map": "https://map.kakao.com/?q=" + urllib.parse.quote(v["n"]),
            "tel": d.get("tel") or "",
        })

    places.sort(key=lambda x: (-x["mentions"], -(x.get("rc") or 0)))
    top = places[:10]

    # 화제어 from extracted candidate names (not only validated)
    kw_counts = {}
    for name, m in cands.items():
        total = m["news"] + m["blog"] + m["youtube"]
        if total < 1 or name in STOP:
            continue
        kw_counts[name] = kw_counts.get(name, 0) + total
    # also boost validated place short names
    for p in top:
        short = re.sub(r"\s*(본점|[가-힣A-Za-z0-9]+점)$", "", p["n"]).strip()
        kw_counts[short] = max(kw_counts.get(short, 0), p["mentions"])
    keywords = []
    for k, n in sorted(kw_counts.items(), key=lambda x: -x[1])[:10]:
        prev_n = prev_kw.get(k, 0)
        ch = n - prev_n
        keywords.append({"k": k, "n": n, "ch": ch, "arrow": "▲" if ch > 0 else ("▼" if ch < 0 else "–")})

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "basis": "뉴스·블로그·유튜브 최근 7일에서 상호 발견 → 카카오 부산 장소 검증 (틱톡 제외)",
        "sources": src_ok,
        "places": top,
        "keywords": keywords,
    }

    if len(top) < 3 and (prev.get("places") or []):
        log("too few validated (%d), keep previous" % len(top))
        out["places"] = prev["places"]
        out["note"] = "이번 카카오 검증 부족 → 직전 순위 유지"

    open(OUT, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))
    log("HOT TOP", len(out["places"]), "kw", len(keywords))
    for i, p in enumerate(out["places"][:8], 1):
        log(f"{i}. {p['n']} mentions={p['mentions']} by={p['by']} ★{p.get('sc')} {p.get('c')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
