#!/usr/bin/env python3
"""👨‍👩‍👧 가족외식 TOP 10
우선 food.json에서 가족·룸·주차·단체·한정식·갈비·뷔페 키워드 후보를 고르고
(가능하면) 카카오 검색으로 보강한 뒤
방문추세+리뷰+평점+블로그로 순위 → food.json['family']"""
from __future__ import annotations
import json, os, re, sys, time, urllib.parse, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FJ = os.path.join(ROOT, "food.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
HS = {"Referer": "https://map.kakao.com/", "User-Agent": "Mozilla/5.0"}
KW = re.compile(r"가족|외식|룸|단체|한정식|갈비|뷔페|코스요리|한우|보양|삼계|룸식|주차|회식|대청|한정식당")
GOOD_C = {"한식", "서양식", "일식", "중식", "기타"}
CHAIN = re.compile(r"맥도날드|버거킹|롯데리아|KFC|빕스|아웃백|애슐리|쿠우쿠우|명륜진사|두끼|본죽|한솥|김밥천국|서브웨이")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def jget(url, h):
    for i in range(2):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15))
        except Exception:
            time.sleep(1 + i)
    return None


def pct_map(vals):
    xs = sorted(vals)
    n = len(xs) or 1
    return {v: round(100 * sum(1 for x in xs if x <= v) / n) for v in set(vals)}


def kakao_boost(existing_ids):
    """Optional: search Kakao for family keywords. Returns set of confirmids."""
    found = set()
    qs = ["부산 가족외식", "부산 한정식", "부산 갈비", "부산 뷔페 가족", "부산 룸 식당"]
    for q in qs:
        j = jget(
            "https://search.map.kakao.com/mapsearch/map.daum?callback=&q=%s&msFlag=A&sort=0&page=1"
            % urllib.parse.quote(q),
            HS,
        )
        if not j:
            continue
        for x in j.get("place") or []:
            if not isinstance(x, dict):
                continue
            pid = str(x.get("confirmid") or "")
            name = x.get("name") or ""
            if not pid or CHAIN.search(name):
                continue
            if not (x.get("address") or "").startswith("부산"):
                continue
            found.add(pid)
        time.sleep(0.25)
    log("kakao family hits", len(found), "overlap", len(found & existing_ids))
    return found


def main():
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    db = json.load(open(FJ, encoding="utf-8"))
    pool = list(db.get("food") or []) + list(db.get("chinese") or [])
    by_id = {str(p["id"]): p for p in pool}

    boost = set()
    try:
        boost = kakao_boost(set(by_id))
    except Exception as e:
        log("kakao skip", e)

    cand = []
    for p in pool:
        if CHAIN.search(p.get("n") or ""):
            continue
        if p.get("c") == "카페" or p.get("c") == "스시뷔페":
            continue
        blob = " ".join([
            p.get("n") or "", p.get("kc") or "", p.get("c") or "",
            " ".join(x[0] for x in (p.get("m") or [])[:6] if x),
            " ".join((p.get("sm") or [])[:3]),
        ])
        hit = 1 if KW.search(blob) else 0
        if str(p["id"]) in boost:
            hit += 2
        # 한식/갈비/뷔페/한정식 성향 + 리뷰 충분
        if hit == 0 and p.get("c") == "한식" and (p.get("rc") or 0) >= 100:
            hit = 1
        if hit == 0:
            continue
        vi = p.get("vi") or p.get("ip") or 0
        cand.append({
            "id": str(p["id"]),
            "n": p["n"],
            "gu": p.get("gu") or p.get("a") or "",
            "c": p.get("c") or "",
            "kc": p.get("kc") or "",
            "addr": p.get("addr") or "",
            "tel": p.get("tel") or "",
            "rc": p.get("rc") or 0,
            "sc": p.get("sc") or 0,
            "bl": p.get("bl") or 0,
            "vi": vi,
            "im": p.get("im"),
            "ims": (p.get("ims") or [])[:5],
            "m": p.get("m") or [],
            "sm": (p.get("sm") or [])[:2],
            "h": p.get("h") or [],
            "hit": hit,
        })

    if len(cand) < 8:
        # broaden: top 한식 by reviews
        for p in sorted(pool, key=lambda x: -((x.get("rc") or 0) + (x.get("bl") or 0))):
            if p.get("c") != "한식":
                continue
            if any(c["id"] == str(p["id"]) for c in cand):
                continue
            cand.append({
                "id": str(p["id"]), "n": p["n"], "gu": p.get("gu") or p.get("a") or "",
                "c": p.get("c"), "kc": p.get("kc"), "addr": p.get("addr"), "tel": p.get("tel"),
                "rc": p.get("rc") or 0, "sc": p.get("sc") or 0, "bl": p.get("bl") or 0,
                "vi": p.get("vi") or p.get("ip") or 0, "im": p.get("im"),
                "ims": (p.get("ims") or [])[:5], "m": p.get("m") or [],
                "sm": (p.get("sm") or [])[:2], "h": p.get("h") or [], "hit": 1,
            })
            if len(cand) >= 40:
                break

    pv = pct_map([c["vi"] for c in cand])
    pr = pct_map([c["rc"] for c in cand])
    ps = pct_map([c["sc"] for c in cand])
    pb = pct_map([c["bl"] for c in cand])
    for c in cand:
        hit_b = min(100, c["hit"] * 30)
        c["fs"] = round(0.35 * pv[c["vi"]] + 0.25 * pr[c["rc"]] + 0.20 * ps[c["sc"]] + 0.15 * pb[c["bl"]] + 0.05 * hit_b)
        c["basis"] = "카카오 방문추세 35% + 리뷰 25% + 평점 20% + 블로그 15% + 가족키워드 5%"
        c["map"] = "https://map.kakao.com/?q=" + urllib.parse.quote(c["n"])

    cand.sort(key=lambda x: (-x["fs"], -x["rc"]))
    top, seen = [], set()
    for c in cand:
        k = re.sub(r"\s+", "", c["n"])
        if k in seen:
            continue
        seen.add(k)
        top.append(c)
        if len(top) >= 10:
            break

    db["family"] = top
    db["family_updated"] = today
    # preserve fishmarkets etc.
    open(FJ, "w", encoding="utf-8").write(json.dumps(db, ensure_ascii=False, separators=(",", ":")))
    log("family", len(top), today)
    for i, p in enumerate(top, 1):
        log(f"{i}. {p['n']} fs={p['fs']} ★{p['sc']} 리뷰{p['rc']}")


if __name__ == "__main__":
    main()
