#!/usr/bin/env python3
"""부산 행사 '속보' 텔레그램 알림 (30분 간격, 표준 라이브러리만 사용).

감지 대상
 (a) 갑자기 생긴 행사: Visit Busan(이번 달·다음 달 목록)·벡스코(목록 1~2쪽)에서 처음 보는 행사 중 14일 안에 시작
 (b) 뉴스 속보: Google News RSS(최근 48시간)에서 부산 + 버스킹/게릴라/깜짝 공연, 또는 부산 + 가수·밴드 + 출연/무료공연
 (c) 출연진 추가 공개: events.json의 기존 행사에 새로 추가된 출연진 (이전 실행 스냅샷과 비교)
상태: data/breaking_sent.json (첫 실행은 조용히 기준만 저장). 1회 최대 5건.
사용: python3 scripts/breaking.py [--dry-run] [--seed]
"""
import json, os, re, sys, html, time, datetime, argparse, hashlib, urllib.parse
import email.utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_events as U  # noqa: E402
from notify_telegram import send, esc, when, APP  # noqa: E402

ROOT = U.ROOT
STATE = os.path.join(ROOT, "data", "breaking_sent.json")
NOTIFIED = os.path.join(ROOT, "data", "notified.json")
EVENTS = os.path.join(ROOT, "events.json")
MAX_SEND = 5
SOON_DAYS = 14
NEWS_HOURS = 48
QUERIES = ["부산 버스킹 가수", "부산 깜짝 공연", "부산 게릴라 공연", "해운대 버스킹", "광안리 버스킹",
           "서면 버스킹", "부산 축제 출연 가수 확정", "부산 무료공연 가수"]
BUSAN = r"부산|해운대|광안리|광안대교|서면|남포동|BIFF광장|자갈치|기장|송정|영도|다대포|동래|센텀|벡스코|사직|태종대|감천"
STRONG = r"버스킹|게릴라\s*공연|깜짝\s*공연|기습\s*공연|깜짝\s*무대|거리\s*공연"
ARTIST = r"가수|아이돌|밴드|트로트|싱어송라이터|래퍼|보컬|그룹"
PERFORM = r"출연|무료\s*공연|축하\s*공연|공연\s*확정|라인업|무대|콘서트|버스킹|게릴라|깜짝"
NEG = r"별세|사망|폭행|검거|논란|사고|소송|구속|혐의|음주|부고"


def load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def kst_date(x):
    return datetime.date.fromisoformat(x[:10]) if x and len(x) >= 10 else None


# ── (a) 빠른 소스 ──
def fast_visitbusan():
    out = []
    y, m = U.NOW.year, U.NOW.month
    for _ in range(2):
        try:
            s = U.fetch(U.LIST.format(m=m, y=y, p=1), verify=False, timeout=15)
            for sid, t in re.findall(r'dataSid=(\d+)"\s*title="([^"]*)"', s):
                out.append(("vb" + sid, sid, html.unescape(t).replace(" 바로가기", "")))
        except Exception as e:  # noqa
            U.log("visitbusan list fail", y, m, e)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fast_bexco():
    rows = []
    for p in (1, 2):
        try:
            s = U.fetch(U.BX_LIST.format(p=p), timeout=15)
        except Exception as e:  # noqa
            U.log("bexco list fail", p, e); break
        for chunk in re.split(r'EventScheduleMgr/view\.do\?[^"]*?event_seq=', s)[1:]:
            seq = re.match(r"(\d+)", chunk).group(1)
            chunk = chunk.split("</li>")[0]
            g = lambda c: (lambda mm: html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", mm.group(1))).strip()) if mm else "")(re.search(r'<span class="' + c + r'"[^>]*>(.*?)</span>', chunk, re.S))
            dates = re.findall(r"20\d\d-\d\d-\d\d", g("date"))
            cat = (lambda mm: mm.group(1).strip() if mm else "")(re.search(r'<span class="eventIcon[^"]*">([^<]*)</span>', chunk))
            if not dates or cat in ("회의", "기타"):
                continue
            rows.append({"id": "bx" + seq, "n": g("subject"), "s": dates[0], "e": dates[-1], "p": "벡스코 " + g("place"),
                         "gu": "해운대구", "url": U.BX_VIEW.format(seq=seq)})
    return rows


def detect_events(state, known_all, seed):
    found, ids = [], []
    soon = (U.NOW.date() + datetime.timedelta(days=SOON_DAYS)).isoformat()
    vb = fast_visitbusan()
    bx = fast_bexco()
    ids = [x[0] for x in vb] + [r["id"] for r in bx]
    if seed:
        return [], ids
    new_vb = [x for x in vb if x[0] not in known_all][:6]
    for eid, sid, t in new_vb:
        try:
            ev = U.parse_view(sid)
            ev["url"] = ev.get("u") or ev["srcu"]
        except Exception as e:  # noqa
            U.log("vb view fail", sid, e); continue
        if ev.get("s") and U.TODAY <= (ev.get("e") or ev["s"]) and ev["s"] <= soon:
            found.append(ev)
    for r in bx:
        if r["id"] not in known_all and r["e"] >= U.TODAY and r["s"] <= soon \
                and not re.search(r"채용|설명회|세미나|컨퍼런스|콘퍼런스|포럼|총회|심포지엄|학술|시험|워크숍|교육", r["n"]):
            found.append(r)
    return found, ids


def fmt_event(e):
    L = ["🚨 <b>[속보] 새 행사 등록</b>", "", f"<b>{esc(e['n'])}</b>"]
    meta = " · ".join(x for x in [when(e), e.get("gu", ""), (e.get("p") or "")[:40]] if x)
    if meta:
        L.append("📅 " + esc(meta))
    lu = e.get("lineup") or []
    if lu:
        L.append("🎤 " + esc(" · ".join(x["name"] for x in lu[:5])))
    if e.get("fee"):
        L.append("💰 " + esc(e["fee"][:60]))
    links = []
    if e.get("url"):
        links.append(f'<a href="{html.escape(e["url"])}">출처</a>')
    links.append(f'<a href="{html.escape(APP)}">앱에서 보기</a>')
    L += ["", " · ".join(links)]
    return "\n".join(L)


# ── (b) 뉴스 ──
def news(lineup_names):
    out, seen = [], set()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=NEWS_HOURS)
    for q in QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:2d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        try:
            s = U.fetch(url, tries=1, timeout=15)
        except Exception as e:  # noqa
            U.log("news fail", q, e); continue
        for it in re.findall(r"<item>(.*?)</item>", s, re.S):
            g = lambda t: html.unescape((re.search(f"<{t}(?:\\s[^>]*)?>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
            title, link, pub, src = g("title"), g("link"), g("pubDate"), re.sub(r"<[^>]+>", "", g("source"))
            desc = re.sub(r"<[^>]+>", " ", html.unescape(g("description")))
            try:
                dt = email.utils.parsedate_to_datetime(pub)
            except Exception:
                continue
            if dt < cutoff:
                continue
            head = re.sub(r"\s+-\s+[^-]+$", "", title)  # ' - 언론사' 제거
            key = re.sub(r"[^가-힣A-Za-z0-9]", "", head)[:40]
            if key in seen:
                continue
            seen.add(key)
            text = head + " " + desc
            if not re.search(BUSAN, text) or re.search(NEG, head):
                continue
            strong = re.search(STRONG, head)
            artist = re.search(ARTIST, head) and re.search(PERFORM, head)
            known = [n for n in lineup_names if len(n) >= 2 and n in head]
            if not (strong or artist or (known and re.search(PERFORM, head))):
                continue
            names = known + re.findall(r"(?:가수|트로트\s*가수|밴드|그룹)\s+([가-힣A-Za-z0-9]{2,12})", head)
            names = [n for n in dict.fromkeys(names) if not re.fullmatch(r"공연|출연|무대|버스킹|등|들|페스티벌|축제", n)]
            out.append({"key": "n:" + hashlib.md5(key.encode()).hexdigest()[:12], "head": head, "src": src,
                        "link": link, "dt": dt.astimezone(U.KST), "names": names[:5]})
        time.sleep(0.5)
    return out


def fmt_news(n):
    L = ["🚨 <b>[속보] 부산 공연·버스킹 소식</b>", "", f"<b>{esc(n['head'])}</b>"]
    if n["names"]:
        L.append("🎤 " + esc(" · ".join(n["names"])) + " (기사 제목 기준)")
    L.append("📰 " + esc(n["src"] or "뉴스") + " · " + n["dt"].strftime("%m.%d %H:%M") + " KST")
    L += ["", f'<a href="{html.escape(n["link"])}">기사 보기</a> · <a href="{html.escape(APP)}">앱에서 보기</a>']
    return "\n".join(L)


# ── (c) 출연진 추가 ──
def fmt_lineup(e, added):
    L = ["🚨 <b>[속보] 출연진 추가 공개</b>", "", f"<b>{esc(e['n'])}</b>",
         "🎤 " + esc(" · ".join(added))]
    meta = " · ".join(x for x in [when(e), e.get("gu", ""), (e.get("p") or "")[:40]] if x)
    if meta:
        L.append("📅 " + esc(meta))
    src = (e.get("lineup") or [{}])[0].get("srcu") or e.get("url") or ""
    links = ([f'<a href="{html.escape(src)}">출처</a>'] if src else []) + [f'<a href="{html.escape(APP + "#event-" + urllib.parse.quote(e["id"]))}">앱에서 보기</a>']
    L += ["", " · ".join(links)]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true", help="보내지 않고 현재 상태만 기준으로 저장")
    a = ap.parse_args()
    t0 = time.time()
    state = load(STATE, {})
    seed = a.seed or not state.get("seeded")
    events = load(EVENTS, {}).get("events", [])
    notified = load(NOTIFIED, {})
    known_all = set(state.get("event_ids", [])) | set(notified.get("known_ids", [])) | {e["id"] for e in events}
    # 다른 소스에서 이미 같은 행사가 있으면 새 행사로 보지 않음
    lineups_now = {e["id"]: [x["name"] for x in (e.get("lineup") or [])] for e in events}
    lineup_names = sorted({n for v in lineups_now.values() for n in v}, key=len, reverse=True)

    found, ids = detect_events(state, known_all, seed)
    found = [f for f in found if not any(U.same(f, e) for e in events)]
    items = news(lineup_names)
    sent_news = set(state.get("news", []))
    new_news = [n for n in items if n["key"] not in sent_news]
    prev_lu = state.get("lineups", {})
    lu_adds = []
    for e in events:
        if e["id"] in prev_lu:
            added = [n for n in lineups_now[e["id"]] if n not in prev_lu[e["id"]]]
            if added and (e.get("e") or e.get("s") or "9999") >= U.TODAY:
                lu_adds.append((e, added))

    msgs = []
    if not seed:
        msgs = [("ev", f, fmt_event(f)) for f in found] + [("lu", x, fmt_lineup(*x)) for x in lu_adds] + \
               [("news", n, fmt_news(n)) for n in sorted(new_news, key=lambda n: n["dt"], reverse=True)]
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    sent_ev, sent_n, sent_lu = [], [], []
    for kind, obj, text in msgs[:MAX_SEND]:
        if not a.dry_run and not (token and chat):
            print("TELEGRAM_BOT_TOKEN/CHAT_ID 없음 → 전송 생략"); break
        if send(text, token, chat, a.dry_run):
            if kind == "ev":
                sent_ev.append(obj["id"])
            elif kind == "news":
                sent_n.append(obj["key"])
            else:
                sent_lu.append(obj[0]["id"])
        time.sleep(1)
    if a.dry_run:
        print(f"(dry-run) 감지: 새 행사 {len(found)} · 출연진 추가 {len(lu_adds)} · 뉴스 {len(new_news)} · seed={seed}")
        return 0
    # 상태 저장: 못 보낸 항목(1회 5건 초과·전송 실패)은 기록하지 않아 다음 실행에서 다시 시도
    unsent_ev = {f["id"] for f in found} - set(sent_ev)
    ev_ids = (set(state.get("event_ids", [])) | set(ids)) - unsent_ev
    news_keys = sent_news | ({n["key"] for n in items} if seed else set(sent_n))
    snap = dict(lineups_now)
    for e, _ in lu_adds:
        if e["id"] not in sent_lu and not seed:
            snap[e["id"]] = prev_lu[e["id"]]
    new_state = {"seeded": True, "updated": U.NOW.strftime("%Y-%m-%d %H:%M"),
                 "note": "속보 알림 상태: event_ids=본 행사 id, news=보낸/본 뉴스 키, lineups=행사별 출연진 스냅샷",
                 "event_ids": sorted(ev_ids), "news": sorted(news_keys)[-600:], "lineups": snap}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=0)
    if sent_ev:  # 아침 '새 행사' 알림에서 다시 보내지 않도록
        notified["known_ids"] = sorted(set(notified.get("known_ids", [])) | set(sent_ev))
        with open(NOTIFIED, "w", encoding="utf-8") as f:
            json.dump(notified, f, ensure_ascii=False, indent=1)
    print(f"seed={seed} 새 행사 {len(found)} · 출연진 추가 {len(lu_adds)} · 뉴스 {len(new_news)} · 전송 {len(sent_ev) + len(sent_n)} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
