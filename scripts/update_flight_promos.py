#!/usr/bin/env python3
"""부산 관련 항공사 특가·프로모션 수집 (매시간).

공식 이벤트 페이지는 다수 403/JS라 Google News RSS를 주 소스로 쓰고,
열리는 공식 페이지는 보조로 훑습니다. 첫 실행은 baseline(알림 없음).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tg_style import send as _tg_send, frame, join_items, esc  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}
OUT = "flight_promos.json"
SEEN = "data/flight_promos_seen.json"
APP = "https://dlfmzlspdh764-svg.github.io/busan-guide/#flight"

AIRLINES = [
    ("에어부산", "airbusan"),
    ("제주항공", "jejuair"),
    ("진에어", "jinair"),
    ("이스타항공", "eastarjet"),
    ("티웨이항공", "twayair"),
    ("대한항공", "koreanair"),
    ("비엣젯", "vietjet"),
    ("베트남항공", "vietnamairlines"),
]

# 보조: 열리는 공식 페이지 (실패해도 무시)
OFFICIAL = [
    ("제주항공", "https://www.jejuair.net/ko/event/event.do"),
    ("티웨이항공", "https://www.twayair.com/app/promotion/event/ongoing"),
]

KW = re.compile(r"(특가|프로모션|할인|이벤트|항공권|프로모|세일|찜|진마켓|슈스페)")
GEO_PUS = re.compile(r"(부산|김해|PUS|김해공항)")
GEO_THVN = re.compile(
    r"(태국|방콕|치앙마이|푸껫|베트남|다낭|나트랑|푸꾸옥|하노이|호치민|호찌민|"
    r"BKK|CNX|DAD|CXR|PQC|HAN|SGN|방콕|동남아)"
)
SKIP = re.compile(r"(채용|화물|사고|지연|결항|파업|실적|주가|IR |공시)")


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def gid(*parts) -> str:
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    return h


def parse_rss(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = strip_html(it.findtext("description") or "")
        pub = it.findtext("pubDate") or ""
        dt = None
        if pub:
            try:
                dt = parsedate_to_datetime(pub).astimezone(KST)
            except Exception:
                dt = None
        items.append({"title": title, "url": link, "desc": desc[:240], "pub": dt})
    return items


def from_rss(airline: str):
    q = urllib.parse.quote(f"{airline} 특가 OR 프로모션 OR 할인 항공권")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        raw = fetch(url)
        items = parse_rss(raw)
    except Exception as e:
        print("rss fail", airline, type(e).__name__)
        return [], "rss_fail"
    out = []
    cutoff = NOW - timedelta(days=14)
    for it in items[:25]:
        t = it["title"]
        if SKIP.search(t):
            continue
        if not KW.search(t) and not KW.search(it["desc"]):
            continue
        if it["pub"] and it["pub"] < cutoff:
            continue
        # strip " - 언론사" suffix for id stability
        bare = re.sub(r"\s*[-–|]\s*[^-–|]{2,30}$", "", t).strip()
        pid = gid(airline, bare.lower())
        flags = []
        blob = t + " " + it["desc"]
        if GEO_PUS.search(blob):
            flags.append("부산")
        if GEO_THVN.search(blob):
            flags.append("태국·베트남")
        out.append({
            "id": pid,
            "airline": airline,
            "title": bare[:120],
            "url": it["url"],
            "source": "Google News",
            "pub": it["pub"].strftime("%Y-%m-%d") if it["pub"] else None,
            "flags": flags,
            "snippet": it["desc"][:160],
        })
    return out, "rss_ok"


def from_official(airline: str, url: str):
    try:
        html = fetch(url, timeout=15).decode("utf-8", "replace")
    except Exception as e:
        print("official fail", airline, type(e).__name__)
        return [], "official_fail"
    # crude: extract event-like titles from anchors / headings
    cands = re.findall(
        r"(?:<(?:a|h[1-4]|strong|p)[^>]*>)([^<]{8,80})<",
        html, re.I,
    )
    out = []
    for raw in cands:
        t = strip_html(raw)
        if not KW.search(t):
            continue
        if SKIP.search(t):
            continue
        if airline[:2] not in t and "특가" not in t and "프로모" not in t and "이벤트" not in t:
            continue
        pid = gid(airline, "off", t.lower()[:80])
        flags = []
        if GEO_PUS.search(t):
            flags.append("부산")
        if GEO_THVN.search(t):
            flags.append("태국·베트남")
        out.append({
            "id": pid,
            "airline": airline,
            "title": t[:120],
            "url": url,
            "source": "항공사 이벤트 페이지",
            "pub": None,
            "flags": flags,
            "snippet": "",
        })
    # dedupe by title
    seen, uniq = set(), []
    for p in out:
        if p["title"] in seen:
            continue
        seen.add(p["title"]); uniq.append(p)
    return uniq[:8], "official_ok"


def main():
    seen = load(SEEN, {"ids": [], "first": None})
    first = not seen.get("ids")
    sources = {}
    found = []
    for name, _ in AIRLINES:
        items, st = from_rss(name)
        sources[name] = st
        found.extend(items)
        time.sleep(0.3)
    for name, url in OFFICIAL:
        items, st = from_official(name, url)
        sources[name + "_official"] = st
        found.extend(items)

    # dedupe by id
    by_id = {}
    for p in found:
        by_id.setdefault(p["id"], p)
    # near-dupe collapse: same airline + normalized title
    def norm(s):
        s = re.sub(r"[\s\"'‘’“”·…\-–—]+", "", s or "")
        return s[:40]
    seen_n, promos = set(), []
    for p in by_id.values():
        k = p["airline"] + "|" + norm(p["title"])
        if k in seen_n:
            continue
        seen_n.add(k)
        promos.append(p)
    # prefer PUS / THVN flagged first, then recent
    promos.sort(key=lambda p: (
        0 if "부산" in p["flags"] else 1,
        0 if "태국·베트남" in p["flags"] else 1,
        p["pub"] or "0000",
    ), reverse=False)
    # actually want recent first among same flag — fix sort
    promos.sort(key=lambda p: (
        0 if "부산" in p["flags"] else 1,
        0 if "태국·베트남" in p["flags"] else 1,
        -(int((p["pub"] or "2000-01-01").replace("-", "") or 0)),
    ))

    known = set(seen.get("ids") or [])
    new = [p for p in promos if p["id"] not in known]
    if first:
        print("baseline", len(promos), "ids — no telegram")
        seen = {"ids": [p["id"] for p in promos], "first": NOW.strftime("%Y-%m-%d %H:%M"), "sources": sources}
        new = []
    else:
        # keep last 400 ids
        ids = list(dict.fromkeys([p["id"] for p in promos] + list(known)))[:400]
        seen = {"ids": ids, "first": seen.get("first"), "checked": NOW.strftime("%Y-%m-%d %H:%M"), "sources": sources}

    # UI list: top 20 recent/relevant
    ui = {
        "updated": NOW.strftime("%Y-%m-%d %H:%M"),
        "source": "Google News RSS + 항공사 이벤트 페이지(가능한 경우)",
        "items": promos[:20],
        "sources": sources,
    }
    json.dump(ui, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(seen, open(SEEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("promos", len(promos), "new", len(new), "sources", sources)

    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if new and tok and chat:
        items = []
        for p in new[:8]:
            flag = ""
            if p["flags"]:
                flag = " · " + " · ".join("🏷 " + f for f in p["flags"])
            line = (
                f"✈️ <b>{esc(p['airline'])}</b>{esc(flag)}\n"
                f"{esc(p['title'])}\n"
                f"{esc(p['pub'] or '날짜 미상')} · {esc(p['source'])}\n"
                f"<a href=\"{esc(p['url'])}\">기사·이벤트 보기</a>"
            )
            items.append(line)
        _tg_send(
            frame(
                "flight_promo",
                join_items(items),
                subtitle="부산·태국·베트남 관련 가능 · 직항 요금과 별도",
                footer_extra=f'<a href="{esc(APP)}">앱 항공편 탭</a>',
            ),
            tok, chat, False,
        )
    elif new:
        print("telegram skip (no token) new=", len(new))


if __name__ == "__main__":
    main()
