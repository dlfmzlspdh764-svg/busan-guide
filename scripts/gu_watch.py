#!/usr/bin/env python3
"""구·군청·문화회관 게시판 실시간 추적 (1시간 간격, 표준 라이브러리만).

update_events.py의 GU_SOURCES/스크래퍼를 그대로 재사용해 게시판 1쪽만 빠르게 읽고,
events.json에 없던 행사성 글을 바로 추가(기존 데이터는 유지)하고 텔레그램 🚨 속보를 보냅니다.
추가로 날짜 미정(YYYY-MM / N월 중) 행사의 출처 페이지를 소량 재확인해 구체 날짜가
나오면 events.json을 갱신하고 📅 날짜 확정 알림을 보냅니다.
상태: data/gu_watch.json (첫 실행은 조용히 기준만 저장). 1회 최대 5건 전송(+날짜확정 최대 5).
사용: python3 scripts/gu_watch.py [--dry-run] [--seed]
"""
import html, json, os, sys, time, argparse, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_events as U  # noqa: E402
from notify_telegram import send, when, APP  # noqa: E402
from breaking import fmt_event  # noqa: E402

STATE = os.path.join(U.ROOT, "data", "gu_watch.json")
NOTIFIED = os.path.join(U.ROOT, "data", "notified.json")
MAX_SEND = 5
TBD_FETCH_MAX = 10   # 시간당 출처 재확인 상한(저비용)
TBD_ALERT_MAX = 5
U.GU_VIEW_MAX = 8
U.GU_BUDGET = 45


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def fmt_date_confirmed(e, old_s):
    link = f'{APP}#event-{urllib.parse.quote(e["id"])}'
    lines = [
        "📅 <b>날짜 확정</b>",
        f"<b>{html.escape(e.get('n') or '')}</b>",
        f"이전: {html.escape(old_s)}월 중 → 확정: {html.escape(when(e))}",
    ]
    if e.get("gu"):
        lines.append(html.escape(e["gu"]) + (f" · {html.escape(e['p'][:40])}" if e.get("p") else ""))
    lu = e.get("lineup") or []
    if lu:
        lines.append("🎤 " + html.escape(" · ".join(x["name"] for x in lu[:4])))
    lines.append(f'<a href="{html.escape(link)}">앱에서 보기</a>')
    if e.get("srcu") or e.get("url"):
        lines.append(f'<a href="{html.escape(e.get("url") or e.get("srcu"))}">출처</a>')
    return "\n".join(lines)


def upgrade_date(e, s, en, confirmed_list):
    old = e.get("s")
    if len(old or "") != 7 or len(s) != 10:
        return False
    e["s"], e["e"] = s, en or s
    e["st"] = "confirmed"
    e["chk"] = U.TODAY
    confirmed_list.append((e, old))
    return True


def resolve_tbd_batch(events):
    """날짜 미정 행사 출처를 소량 재확인. [(event, old_s), ...]"""
    out = []
    cands = [e for e in events if len(e.get("s") or "") == 7 and (e.get("srcu") or e.get("url"))]
    # check 우선, 그다음 일반, expected는 상세 URL만
    def rank(e):
        st = e.get("st") or ""
        url = (e.get("srcu") or e.get("url") or "").lower()
        detail = 0 if ("view" in url or "detail" in url or "fstvl" in url) else 1
        pri = 0 if st == "check" else (1 if st != "expected" else 2)
        return (pri, detail, e.get("s") or "", e.get("n") or "")
    cands.sort(key=rank)
    n_fetch = 0
    for e in cands:
        if n_fetch >= TBD_FETCH_MAX:
            break
        if e.get("st") == "expected":
            url = (e.get("srcu") or "").lower()
            if "view" not in url and "detail" not in url and "fstvl" not in url:
                continue
        n_fetch += 1
        rng = U.resolve_tbd_event(e)
        if not rng:
            continue
        upgrade_date(e, rng[0], rng[1], out)
        time.sleep(0.3)
    print(f"tbd 재확인 {n_fetch}건 · 날짜 확정 {len(out)}건")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    data = load(U.OUT, None)
    if not data or len(data.get("events", [])) < 20:
        print("events.json 없음/비정상 → 중단"); return 0
    events = data["events"]
    state = load(STATE, {})
    seed = a.seed or not state.get("seeded")
    status = {}
    found = U.run_gu_sources(events, status)
    ids = {e["id"] for e in events}
    seen = set(state.get("seen", []))
    added = []
    date_hits = []
    for v in found:
        hit = next((e for e in events + added if e.get("id") == v.get("id") or U.same(v, e)), None)
        if hit:
            # 기존 미정 일정에 새 스크랩이 구체 날짜를 가져오면 업그레이드
            if len(hit.get("s") or "") == 7 and len(v.get("s") or "") == 10:
                upgrade_date(hit, v["s"], v.get("e") or v["s"], date_hits)
            U.merge_into(hit, v)
            if v.get("type") == "콘서트":
                hit["type"] = "콘서트"
            continue
        if v["id"] in ids:
            continue
        added.append(dict(v))
    if added:
        U.finalize_schema(added)
        events += added
        events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))

    # 날짜 미정 재확인 (저비용)
    date_hits += resolve_tbd_batch(events)
    # 중복 제거 (같은 id)
    seen_ids, uniq_hits = set(), []
    for e, old in date_hits:
        if e["id"] in seen_ids:
            continue
        seen_ids.add(e["id"]); uniq_hits.append((e, old))
    date_hits = uniq_hits

    data.setdefault("status", {}).update(status)
    data["gu_watch"] = {"checked": U.NOW.strftime("%Y-%m-%d %H:%M"),
                        "reachable": sorted(k for k, v in status.items() if v.get("ok") or v.get("kept_previous") and "error" not in v),
                        "unreachable": sorted(k for k, v in status.items() if "error" in v),
                        "tbd_resolved": len(date_hits)}
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    sent = []
    if not seed:
        for e in [x for x in added if x["id"] not in seen][:MAX_SEND]:
            if not a.dry_run and not (token and chat):
                print("텔레그램 설정 없음 → 전송 생략"); break
            if send(fmt_event(e).replace("[속보] 새 행사 등록", "[속보] 구·군청 새 행사"), token, chat, a.dry_run):
                sent.append(e["id"])
            time.sleep(1)
    # 날짜 확정 알림
    nstate = load(NOTIFIED, {})
    already = set(nstate.get("date_confirmed", []))
    date_sent = []
    if not seed:
        for e, old in date_hits:
            if e["id"] in already:
                continue
            if len(date_sent) >= TBD_ALERT_MAX:
                break
            if not a.dry_run and not (token and chat):
                break
            if send(fmt_date_confirmed(e, old), token, chat, a.dry_run):
                date_sent.append(e["id"])
            time.sleep(1)

    if a.dry_run:
        print(f"(dry-run) 새 행사 {len(added)}건 seed={seed}", [e["n"] for e in added])
        print(f"(dry-run) 날짜 확정 {len(date_hits)}건", [(e["n"], old, e["s"]) for e, old in date_hits])
        return 0

    unsent = {e["id"] for e in added} - set(sent) if not seed else set()
    allids = (seen | {e["id"] for e in events if (e.get("origin") or "").startswith("gu:")}) - unsent
    json.dump({"seeded": True, "seen": sorted(allids)},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    changed = bool(added or date_hits)
    if changed:
        U.finalize_schema(events)
        events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))
        data["events"] = events
        data["updated"] = U.NOW.strftime("%Y-%m-%d %H:%M")
        tmp = U.OUT + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.load(open(tmp, encoding="utf-8"))
        os.replace(tmp, U.OUT)

    if sent or date_sent:
        n = load(NOTIFIED, {})
        n["known_ids"] = sorted(set(n.get("known_ids", [])) | set(sent))
        n["date_confirmed"] = sorted(set(n.get("date_confirmed", [])) | set(date_sent))
        # keep list bounded
        n["date_confirmed"] = n["date_confirmed"][-400:]
        json.dump(n, open(NOTIFIED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"seed={seed} 새 행사 {len(added)} · 전송 {len(sent)} · 날짜확정 {len(date_hits)}/{len(date_sent)} · 접속 실패 {data['gu_watch']['unreachable']} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
