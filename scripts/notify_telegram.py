#!/usr/bin/env python3
"""부산 행사 텔레그램 알림 (표준 라이브러리만 사용).

- 매일 아침 다이제스트: 오늘부터 7일 안에 시작하는 행사 (월요일엔 '이번 주 요약' 형식)
- 새 행사 알림: 지난 실행 이후 events.json에 새로 추가된 행사(날짜 확인된 것)만
- 이미 보낸 항목·날짜는 data/notified.json에 기록해 중복 전송하지 않음
- 보낼 내용이 없으면 아무것도 보내지 않음

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (토큰은 절대 출력하지 않음)
사용: python3 scripts/notify_telegram.py [--mode auto|digest|new|weekly] [--force] [--dry-run]
"""
import json, os, sys, html, datetime, urllib.request, urllib.parse, urllib.error, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "events.json")
STATE = os.path.join(ROOT, "data", "notified.json")
APP = "https://dlfmzlspdh764-svg.github.io/busan-guide/"
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
TODAY = NOW.date()
DOW = "월화수목금토일"
LIMIT = 3900  # 텔레그램 4096자 제한 여유


def d(x):
    try:
        return datetime.date.fromisoformat(x[:10]) if x and len(x) >= 10 else None
    except ValueError:
        return None


def dl(x):
    return f"{x.month}.{x.day}({DOW[x.weekday()]})"


def when(e):
    s, en = d(e.get("s")), d(e.get("e")) or d(e.get("s"))
    if not s:
        return e.get("s") or ""
    return dl(s) if not en or en == s else f"{dl(s)}~{dl(en)}"


def esc(x):
    return html.escape(str(x or ""), quote=False)


def item(e, new=False):
    lines = [("🆕 " if new else "• ") + f"<b>{esc(e['n'])}</b>"]
    meta = [when(e), e.get("gu", "")]
    if e.get("p"):
        meta.append(e["p"][:40])
    lines.append("   " + esc(" · ".join(x for x in meta if x)))
    lu = e.get("lineup") or []
    if lu:
        names = " · ".join(x["name"] for x in lu[:3]) + (f" 외 {len(lu) - 3}" if len(lu) > 3 else "")
        lines.append("   🎤 " + esc(names))
    links = [f'<a href="{html.escape(APP + "#event-" + urllib.parse.quote(e["id"]))}">앱에서 보기</a>']
    if e.get("url"):
        links.append(f'<a href="{html.escape(e["url"])}">공식</a>')
    lines.append("   " + " · ".join(links))
    return "\n".join(lines)


def chunks(header, items, footer=""):
    out, cur = [], header
    for it in items:
        if len(cur) + len(it) + 2 > LIMIT:
            out.append(cur)
            cur = header.split("\n")[0] + " (계속)"
        cur += "\n\n" + it
    if footer:
        if len(cur) + len(footer) + 2 > LIMIT:
            out.append(cur); cur = footer
        else:
            cur += "\n\n" + footer
    out.append(cur)
    return out


def send(text, token, chat, dry):
    if dry:
        print("----- (dry-run) -----\n" + text)
        return True
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
    except urllib.error.HTTPError as ex:  # 토큰이 들어간 URL은 출력하지 않음
        j = {"ok": False, "error_code": ex.code, "description": ex.read().decode(errors="replace")[:200]}
    except Exception as ex:  # noqa
        j = {"ok": False, "description": type(ex).__name__}
    print("telegram:", "ok" if j.get("ok") else f"실패 {j.get('error_code')} {j.get('description')}",
          ("message_id=" + str(j["result"]["message_id"])) if j.get("ok") else "")
    return bool(j.get("ok"))


def usable(e):
    return e.get("st") != "expected" and d(e.get("s")) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="auto", choices=["auto", "digest", "new", "weekly"])
    ap.add_argument("--force", action="store_true", help="오늘 이미 다이제스트를 보냈어도 다시 보냄")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not a.dry_run and (not token or not chat):
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 없음 → 건너뜀")
        return 0
    data = json.load(open(EVENTS, encoding="utf-8"))
    events = [e for e in data.get("events", []) if usable(e)]
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        st = {}
    known = set(st.get("known_ids", []))
    first_run = not known
    sent_any, ok_all = False, True

    # 1) 새 행사 알림 (첫 실행은 기준선만 저장)
    new = []
    if not first_run and a.mode in ("auto", "new"):
        new = [e for e in events if e["id"] not in known and (d(e.get("e")) or d(e.get("s"))) >= TODAY]
        new.sort(key=lambda e: e.get("s") or "")
        if new:
            hdr = f"🆕 <b>부산 새 행사 {len(new)}건</b> (자동 업데이트 {esc(data.get('updated', ''))} KST)"
            for msg in chunks(hdr, [item(e, True) for e in new[:40]],
                              f"…외 {len(new) - 40}건은 앱에서 확인하세요: {APP}#event" if len(new) > 40 else ""):
                ok_all &= send(msg, token, chat, a.dry_run); sent_any = True

    # 2) 아침 다이제스트 (하루 한 번), 월요일은 주간 요약
    mode = a.mode
    if mode == "auto":
        mode = "digest" if (st.get("last_digest") != TODAY.isoformat() or a.force) else "skip"
    if mode in ("digest", "weekly"):
        weekly = mode == "weekly" or (a.mode == "auto" and TODAY.weekday() == 0)
        end = TODAY + datetime.timedelta(days=6)
        up = [e for e in events if TODAY <= d(e["s"]) <= end]
        up.sort(key=lambda e: (e["s"], e["n"]))
        newids = {e["id"] for e in new}
        if up:
            if weekly:
                hdr = f"📅 <b>이번 주 부산 행사 요약</b> {dl(TODAY)}~{dl(end)} · {len(up)}건"
                items, cur = [], None
                for e in up:
                    day = d(e["s"])
                    if day != cur:
                        cur = day; items.append(f"<b>— {dl(day)} —</b>")
                    items.append(item(e, e["id"] in newids))
                gus = {}
                for e in up:
                    gus[e.get("gu", "")] = gus.get(e.get("gu", ""), 0) + 1
                foot = "구·군별: " + esc(", ".join(f"{k} {v}" for k, v in sorted(gus.items(), key=lambda x: -x[1]))) + f"\n전체 일정: {APP}#event"
            else:
                hdr = f"☀️ <b>부산 다가오는 행사</b> (오늘~{dl(end)}) · {len(up)}건"
                items = [item(e, e["id"] in newids) for e in up]
                foot = f"전체 일정: {APP}#event"
            for msg in chunks(hdr, items, foot):
                ok_all &= send(msg, token, chat, a.dry_run); sent_any = True
        else:
            print("7일 안에 시작하는 행사 없음 → 다이제스트 건너뜀")
        if ok_all and not a.dry_run:
            st["last_digest"] = TODAY.isoformat()

    if not sent_any:
        print("보낼 내용 없음")
    if not a.dry_run and ok_all:
        st["known_ids"] = sorted(known | {e["id"] for e in events})
        st["updated"] = NOW.strftime("%Y-%m-%d %H:%M")
        st.setdefault("note", "텔레그램 알림 상태: known_ids=이미 알고 있는 행사 id(새 행사 알림 기준), last_digest=마지막 아침 다이제스트 날짜(KST)")
        tmp = STATE + ".tmp"
        json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        os.replace(tmp, STATE)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
