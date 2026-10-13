#!/usr/bin/env python3
"""부산 관련 뉴스 수집 (Google News RSS, 표준 라이브러리만).

- 주제: 여행 / 맛집 / 명소 / 외국인 / 교통
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
    ("부산 여행", "여행"),
    ("부산 맛집", "맛집"),
    ("부산 관광지", "명소"),
    ("부산 외국인 관광객", "외국인"),
    ("부산 교통", "교통"),
]

EXCLUDE = re.compile(
    r"살인|강도|성폭|성추|성희|납치|폭행|사망|숨져|숨진|시신|부고|별세|"
    r"교통사고|추돌|충돌사고|화재|실종|검거|피의자|체포|재판|구속|"
    r"마약|음주운전|자살|흉기|칼부림|총기",
    re.I,
)


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
            if EXCLUDE.search(title):
                continue
            key = re.sub(r"\s+", "", title.lower())
            if key in seen:
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
                    "topic": topic,
                }
            )
        time.sleep(0.4)
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    return items[:30]


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
