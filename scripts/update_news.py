#!/usr/bin/env python3
"""부산 관련 뉴스 수집 (Google News RSS, 표준 라이브러리만).

- 주제: 관광/항공/해양/신규오픈/교통/정책/노동/경제 (부산 언급 필수)
- 최근 2일 기사, 제목 중복 제거, 범죄·사고·부고 제외
- 최신순 최대 30건 → news.json
- 수집 실패 시 기존 파일 유지
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
CTX = ssl.create_default_context()

QUERIES = [
    ("부산 관광", "관광"), ("부산 외국인 관광객", "관광"), ("해운대 관광", "관광"),
    ("김해공항 노선", "항공"), ("가덕도신공항", "항공"), ("에어부산", "항공"),
    ("부산항 해양", "해양"), ("부산 해양수도", "해양"), ("부산 크루즈", "해양"),
    ("부산 신규 오픈", "신규오픈"), ("부산 개장", "신규오픈"),
    ("부산 교통", "교통"), ("부산 지하철 버스", "교통"),
    ("부산시 정책", "정책"), ("부산시 추진", "정책"),
    ("부산 노동 일자리", "노동"), ("부산 고용", "노동"),
    ("부산 경제", "경제"), ("부산 기업 투자", "경제"),
]

BUSAN = re.compile(
    r"부산|해운대|수영구|광안|기장|동래|부산진|서면|남포|자갈치|영도|사하|사상|금정|연제|"
    r"강서구|북구 덕천|김해공항|가덕|송도|다대포|태종대|센텀|북항|BEXCO|벡스코|명지|정관|일광|송정|민락"
)
CAT_KW = {
    "관광": r"관광|여행|관광객|축제|명소|투어|외국인|방문객|호텔|숙박",
    "항공": r"항공|공항|노선|취항|직항|에어부산|여객기|운항|가덕도신공항|신공항",
    "해양": r"해양|항만|부산항|크루즈|수산|선박|해운업|해운사|조선업|조선소|해수욕장|바다|어항|여객터미널",
    "신규오픈": r"오픈|개장|개관|문\s?열|신규\s?매장|입점|개점|문을 연|그랜드\s?오픈|첫\s?선",
    "교통": r"교통|지하철|도시철도|버스|BRT|도로|개통|KTX|SRT|트램|철도|택시|환승|주차",
    "정책": r"정책|조례|부산시|시책|지원사업|추진|계획|예산|시정|박형준|구청장|발표|시행",
    "노동": r"노동|일자리|고용|임금|노조|근로|취업|채용|실업|노사",
    "경제": r"경제|투자|기업|산업|수출|매출|금융|유치|지역경제|상권|소상공인|성장률",
}
CAT_RE = {k: re.compile(v, re.I) for k, v in CAT_KW.items()}
CATS = list(CAT_KW)

EXCLUDE = re.compile(
    r"살인|강도|성폭|성추|성희|납치|폭행|사망|숨져|숨진|시신|부고|별세|빈소|"
    r"교통사고|추돌|충돌|화재|불이|실종|검거|피의자|체포|재판|구속|기소|송치|경찰|"
    r"마약|음주운전|자살|흉기|칼부림|총기|사고|"
    r"롯데\s?자이언츠|야구|축구|KBO|K리그|농구|배구|골프대회|선수|감독|승리|패배|홈런|"
    r"열애|결혼|이혼|아이돌|연예|배우|드라마|예능|"
    r"의혹|비리|공천|선거|후보|국회의원|탄핵|고발|"
    r"날씨|기온|비 소식|폭염|한파|태풍|미세먼지|"
    r"광고|분양|청약|특징주|급등|급락|목표주가|주가|코스피|코스닥|종목|로또",
    re.I,
)


def classify(title, desc, hint):
    t = title + " " + desc
    if hint in CAT_RE and CAT_RE[hint].search(title):
        return hint
    for c in CATS:
        if CAT_RE[c].search(title):
            return c
    if hint in CAT_RE and CAT_RE[hint].search(t):
        return hint
    return None


def norm(t):
    return re.sub(r"[^0-9a-z가-힣]", "", t.lower())


def similar(a, b):
    if a in b or b in a:
        return True
    ga = {a[i:i+2] for i in range(len(a)-1)}; gb = {b[i:i+2] for i in range(len(b)-1)}
    return bool(ga and gb) and len(ga & gb) / min(len(ga), len(gb)) > 0.6


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, tries=2, timeout=20):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (busan-guide news bot; +https://github.com/dlfmzlspdh764-svg/busan-guide)"
                },
            )
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def parse_rss_date(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    # RFC 822 variants from Google News
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(KST).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def text(el):
    if el is None or el.text is None:
        return ""
    return html.unescape(el.text).strip()


def source_from_item(item):
    # Google News: <source url="...">조선일보</source>
    src = item.find("source")
    if src is not None and (src.text or "").strip():
        return html.unescape(src.text).strip()
    # fallback: title "… - 매체명"
    t = text(item.find("title"))
    if " - " in t:
        return t.rsplit(" - ", 1)[-1].strip()
    return "뉴스"


def clean_title(t: str) -> str:
    t = html.unescape(t or "").strip()
    # strip trailing " - Source"
    if " - " in t:
        left, right = t.rsplit(" - ", 1)
        if len(right) <= 20:
            t = left.strip()
    return t


def collect():
    items = []
    seen = set()
    for q, topic in QUERIES:
        params = urllib.parse.urlencode(
            {
                "q": f"{q} when:2d",
                "hl": "ko",
                "gl": "KR",
                "ceid": "KR:ko",
            }
        )
        url = "https://news.google.com/rss/search?" + params
        try:
            raw = fetch(url)
            root = ET.fromstring(raw)
        except Exception as e:  # noqa
            log("fetch fail", q, e)
            continue
        channel = root.find("channel")
        if channel is None:
            continue
        for item in channel.findall("item"):
            title = clean_title(text(item.find("title")))
            link = text(item.find("link"))
            if not title or not link:
                continue
            desc = re.sub(r"<[^>]+>", " ", text(item.find("description")))
            if EXCLUDE.search(title):
                continue
            if not BUSAN.search(title + " " + desc):
                continue
            cat = classify(title, desc, topic)
            if not cat:
                continue
            key = norm(title)
            if any(similar(key, k) for k in seen):
                continue
            seen.add(key)
            pub = parse_rss_date(text(item.find("pubDate"))) or datetime.datetime.now(KST).isoformat(
                timespec="seconds"
            )
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source_from_item(item),
                    "published": pub,
                    "topic": cat,
                }
            )
        time.sleep(0.4)
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    return items[:40]


def main():
    prev = None
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:  # noqa
            prev = None
    try:
        items = collect()
    except Exception as e:  # noqa
        log("FATAL", e)
        if prev:
            log("keeping previous news.json")
            return 0
        return 1
    if len(items) < 3:
        log("too few items:", len(items), "— keeping previous")
        if prev:
            return 0
        return 1
    data = {
        "updated": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "items": items,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, OUT)
    log("wrote", len(items), "items →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
