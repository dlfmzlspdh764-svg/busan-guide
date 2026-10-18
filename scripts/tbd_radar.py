#!/usr/bin/env python3
"""날짜 미정(TBD) 행사 레이더 — 30분마다 전체 TBD를 출처·뉴스 RSS로 재확인.

구체 날짜가 나오면 events.json을 즉시 갱신하고 🟧 날짜 확정 텔레그램을 보냅니다.
사용: python3 scripts/tbd_radar.py [--dry-run]
"""
import argparse, html, json, os, re, sys, time, urllib.parse
import email.utils
import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_events as U  # noqa: E402
from notify_telegram import when, APP  # noqa: E402
from tg_style import send, frame, esc  # noqa: E402

NOTIFIED = os.path.join(U.ROOT, "data", "notified.json")
TBD_ALERT_MAX = 8
SLEEP = 0.25


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def fmt_date_confirmed(e, old_s, via="출처"):
    link = f'{APP}#event-{urllib.parse.quote(e["id"])}'
    lines = [
        f"<b>{esc(e.get('n') or '')}</b>",
        f"이전: {esc(old_s)}월 중 → 확정: {esc(when(e))}",
        f"확인 경로: {esc(via)}",
    ]
    if e.get("gu"):
        lines.append(esc(e["gu"]) + (f" · {esc(e['p'][:40])}" if e.get("p") else ""))
    lu = e.get("lineup") or []
    if lu:
        lines.append("🎤 " + esc(" · ".join(x["name"] for x in lu[:4])))
    lines.append(f'<a href="{esc(link)}">앱에서 보기</a>')
    if e.get("srcu") or e.get("url"):
        lines.append(f'<a href="{esc(e.get("url") or e.get("srcu"))}">출처</a>')
    return frame("date_confirm", "\n".join(lines))


def upgrade(e, s, en, hits, via):
    old = e.get("s")
    if len(old or "") != 7 or len(s) != 10:
        return False
    e["s"], e["e"] = s, en or s
    e["st"] = "confirmed"
    e["chk"] = U.TODAY
    e["_via"] = via
    hits.append((e, old, via))
    return True


def news_snippets(name, month_hint):
    """Google News RSS + Naver news HTML에서 제목·요약을 모음."""
    out = []
    q = f"{name} {month_hint} 개최 OR 일정 OR 날짜"
    gurl = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:60d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    )
    try:
        s = U.fetch(gurl, tries=1, timeout=12, verify=True)
        for it in re.findall(r"<item>(.*?)</item>", s or "", re.S)[:8]:
            g = lambda t: html.unescape((re.search(fr"<{t}(?:\s[^>]*)?>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
            title = re.sub(r"\s+-\s+[^-]+$", "", g("title"))
            desc = re.sub(r"<[^>]+>", " ", html.unescape(g("description")))
            out.append(title + "\n" + desc)
    except Exception as ex:
        U.log("tbd news google fail", name[:20], ex)
    # Naver news search (lightweight HTML)
    try:
        nurl = "https://search.naver.com/search.naver?" + urllib.parse.urlencode(
            {"where": "news", "query": f"{name} 일정", "sort": "1"}
        )
        page = U.fetch(nurl, tries=1, timeout=12, verify=True)
        # titles in news area
        for tit in re.findall(r'class="[^"]*news_tit[^"]*"[^>]*>(.*?)</a>', page or "", re.S)[:6]:
            out.append(re.sub(r"<[^>]+>", "", html.unescape(tit)))
        for dsc in re.findall(r'class="[^"]*dsc_txt[^"]*"[^>]*>(.*?)</(?:a|div|span)>', page or "", re.S)[:6]:
            out.append(re.sub(r"<[^>]+>", "", html.unescape(dsc)))
    except Exception as ex:
        U.log("tbd news naver fail", name[:20], ex)
    return out


def resolve_via_news(e):
    s0 = e.get("s") or ""
    if len(s0) != 7:
        return None
    name = (e.get("n") or "").strip()
    if len(name) < 3:
        return None
    year_hint = int(s0[:4])
    month_hint = f"{int(s0[5:7])}월"
    texts = news_snippets(name, month_hint)
    time.sleep(SLEEP)
    # prefer snippets that contain a short form of the name
    key = U.norm(name)[:6]
    for text in texts:
        if key and key not in U.norm(text):
            # still allow if original chars overlap
            if name[:4] not in text and name[:6] not in text:
                continue
        rng = U.parse_range(text, year_hint)
        if not rng:
            continue
        s, en = rng
        # month must be close to TBD month
        try:
            sm = datetime.date.fromisoformat(s0 + "-01")
            sd = datetime.date.fromisoformat(s)
            if abs((sd.year - sm.year) * 12 + sd.month - sm.month) > 2:
                continue
        except ValueError:
            continue
        if s > en:
            s, en = en, s
        return s, en
    return None


def resolve_one(e):
    """출처 페이지 → 뉴스 RSS 순으로 날짜 확정 시도. (s,e,via) or None"""
    rng = U.resolve_tbd_event(e)
    if rng:
        return rng[0], rng[1], "출처 페이지"
    rng = resolve_via_news(e)
    if rng:
        return rng[0], rng[1], "뉴스·검색"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    data = load(U.OUT, None)
    if not data or len(data.get("events", [])) < 20:
        print("events.json 없음/비정상 → 중단"); return 0
    events = data["events"]
    tbds = [e for e in events if len(e.get("s") or "") == 7]
    # rank: check first, detail URL, then others
    def rank(e):
        st = e.get("st") or ""
        url = (e.get("srcu") or e.get("url") or "").lower()
        detail = 0 if ("view" in url or "detail" in url or "fstvl" in url) else 1
        pri = 0 if st == "check" else (1 if st != "expected" else 2)
        return (pri, detail, e.get("s") or "", e.get("n") or "")
    tbds.sort(key=rank)
    hits = []
    checked = 0
    for e in tbds:
        checked += 1
        got = resolve_one(e)
        if got:
            upgrade(e, got[0], got[1], hits, got[2])
        time.sleep(SLEEP)
    # dedupe
    seen, uniq = set(), []
    for e, old, via in hits:
        if e["id"] in seen:
            continue
        seen.add(e["id"]); uniq.append((e, old, via))
    hits = uniq
    print(f"tbd 전체 {checked}건 확인 · 날짜 확정 {len(hits)}건 ({time.time()-t0:.0f}s)")

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    nstate = load(NOTIFIED, {})
    already = set(nstate.get("date_confirmed", []))
    date_sent = []
    for e, old, via in hits:
        if e["id"] in already:
            continue
        if len(date_sent) >= TBD_ALERT_MAX:
            break
        if a.dry_run:
            print("(dry-run)", e["n"], old, "→", e["s"], via); continue
        if not (token and chat):
            print("텔레그램 설정 없음 → 전송 생략"); break
        if send(fmt_date_confirmed(e, old, via), token, chat, False):
            date_sent.append(e["id"])
        time.sleep(1)

    if a.dry_run:
        return 0

    if hits:
        for e, _, _ in hits:
            e.pop("_via", None)
        U.finalize_schema(events)
        events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))
        data["events"] = events
        data["updated"] = U.NOW.strftime("%Y-%m-%d %H:%M")
        data.setdefault("tbd_radar", {})["checked"] = U.NOW.strftime("%Y-%m-%d %H:%M")
        data["tbd_radar"]["resolved"] = len(hits)
        tmp = U.OUT + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.load(open(tmp, encoding="utf-8"))
        os.replace(tmp, U.OUT)

    if date_sent:
        n = load(NOTIFIED, {})
        n["date_confirmed"] = sorted(set(n.get("date_confirmed", [])) | set(date_sent))[-400:]
        json.dump(n, open(NOTIFIED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"전송 {len(date_sent)} · 파일갱신 {bool(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
