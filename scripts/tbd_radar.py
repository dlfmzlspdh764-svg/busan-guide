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


NAME_ALIASES = {
    "부산차이나타운 문화축제": ["제23회 부산차이나타운 문화축제", "차이나타운 문화축제", "부산 차이나타운 특구 문화축제"],
    "제23회 부산차이나타운 문화축제": ["부산차이나타운 문화축제", "차이나타운 문화축제"],
    "옥토버페스타 인 광안리": ["FALL IN GWANGALLI", "폴 인 광안리", "옥토버페스타 광안리"],
    "서면 빛 축제": ["서면빛축제", "2026 서면 빛 축제"],
    "기장붕장어축제in칠암": ["기장붕장어축제", "제20회 기장붕장어축제"],
    "송정 별, 바다 과학축제": ["송정 별바다 과학축제", "송정 밤바다 별빛과학", "별바다 과학축제"],
    "UN평화축제": ["제28회 UN평화축제", "UN 평화축제"],
}


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


def news_snippets(name, month_hint, aliases=None):
    """Google News RSS + Naver news HTML에서 제목·요약을 모음."""
    out = []
    names = [name] + list(aliases or [])
    # try primary then first alias
    qname = names[0]
    for alt in names[1:3]:
        if alt and alt not in qname:
            qname = f"({qname}) OR ({alt})"
            break
    q = f"{qname} {month_hint} 개최 OR 일정 OR 날짜"
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
    aliases = NAME_ALIASES.get(name, [])
    texts = news_snippets(name, month_hint, aliases)
    time.sleep(SLEEP)
    keys = [U.norm(name)[:6]] + [U.norm(a)[:6] for a in aliases]
    keys += [name[:4], name[:6]] + [a[:4] for a in aliases if len(a) >= 4]
    for text in texts:
        nt = U.norm(text)
        if keys and not any((k and (k in nt or k in text)) for k in keys):
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
        s0 = e.get("s") or "9999-99"
        # nearer months first (current month=0, next=1, ...)
        try:
            y, m = int(s0[:4]), int(s0[5:7])
            near = (y - U.NOW.year) * 12 + (m - U.NOW.month)
            if near < 0:
                near = 50 + abs(near)
        except Exception:
            near = 99
        return (near, pri, detail, s0, e.get("n") or "")
    tbds.sort(key=rank)
    hits = []
    checked = 0
    # time box: prefer finishing near-term rather than all 80+ TBD
    deadline = t0 + 12 * 60
    for e in tbds:
        if time.time() > deadline and checked >= 12:
            print(f"시간 제한 → 나머지 TBD {len(tbds)-checked}건 다음 회차로")
            break
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
